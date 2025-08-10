#!/usr/bin/env python3
"""
Long-running match runner for dilemma-bench.

This script:
1. Fetches available models from OpenRouter
2. Creates agents in the database for new models
3. Finds model pairs that haven't played each other
4. Runs matches between them using the Prisoner's Dilemma game
5. Records results and updates ELO ratings
6. Supports graceful shutdown with Ctrl+C
"""

import asyncio
import signal
import sys
import logging
from typing import List, Dict, Tuple
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import argparse
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv
import os
import requests
import textwrap
# Import from our modules
from agent.graph import play_match
from db.definition import (
    create_tables,
    get_or_create_agent, 
    get_or_create_agents,
    get_played_pairs, 
    store_match_result
)

load_dotenv()

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('match_runner.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Global flag for graceful shutdown
shutdown_requested = False


def signal_handler(signum, frame):
    """Handle Ctrl+C gracefully"""
    global shutdown_requested
    logger.info("\n🛑 Shutdown requested. Finishing current match and exiting gracefully...")
    shutdown_requested = True


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


def get_models() -> List[Dict]:
    """Fetch available models from OpenRouter API"""
    try:
        response = requests.get(
            "https://openrouter.ai/api/v1/models/user",
            headers={"Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY')}"},
            timeout=30
        )
        response.raise_for_status()
        models = response.json()["data"]
        logger.info(f"📡 Fetched {len(models)} models from OpenRouter")
        return models
    except Exception as e:
        logger.error(f"❌ Failed to fetch models: {e}")
        return []


class MatchRunner:
    def __init__(self, max_workers: int = 4):
        self.max_workers = max_workers
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.active_matches = 0
        self.lock = threading.Lock()
    
    def find_unplayed_pairs(self, models: List[Dict]) -> List[Tuple[Dict, Dict, str, str]]:
        """Find pairs of models that haven't played each other yet, optimized to avoid provider conflicts"""
        # Create agents for all models in bulk (much more efficient)
        model_to_agent_id = get_or_create_agents(models)
        
        # Get played pairs
        played_pairs = get_played_pairs()
        
        # Filter out problematic models
        ignore_list = ["z-ai/glm-4.5-air:free","openai/gpt-4.1-nano","mistralai/mixtral-8x22b-instruct","thedrummer/unslopnemo-12b","arcee-ai/virtuoso-large","mistralai/mistral-saba","thedrummer/rocinante-12b","openai/o3","openai/o3-pro","openai/codex-mini","openai/o3-mini","openai/o4-mini-high","google/gemini-2.5-pro-exp-03-25","cohere/command-r","microsoft/phi","openai/gpt-4-0314","google/gemini-2.5-pro","qwen/qwen3","meta-llama/llama-3.3-70b-instruct:free","mistralai/mistral-small-3.2-24b-instruct:free","mistralai/mistral-small-3.1-24b-instruct:free","google/gemini-2.0-flash-exp:free","mistralai/devstral-small","nousresearch/hermes-3-llama-3.1-70b"]
        models = [m for m in models if not any([i in m["id"] for i in ignore_list])]
        
        # Find all unplayed pairs first
        all_unplayed_pairs = []
        for i, model1 in enumerate(models):
            for model2 in models[i+1:]:
                agent1_id = model_to_agent_id[model1["id"]]
                agent2_id = model_to_agent_id[model2["id"]]
                
                if (agent1_id, agent2_id) not in played_pairs and (agent2_id, agent1_id) not in played_pairs:
                    all_unplayed_pairs.append((model1, model2, agent1_id, agent2_id))
        
        # Now sort pairs to minimize provider conflicts
        sorted_pairs = self._optimize_pair_ordering(all_unplayed_pairs)
        
        # Log provider diversity stats
        if sorted_pairs:
            # Show spacing analysis for the first batch
            batch_size = min(self.max_workers * 2, len(sorted_pairs))  # Show 2 batches worth
            first_batch = sorted_pairs[:batch_size]
            
            provider_info = []
            provider_positions = {}
            
            for i, (model1, model2, _, _) in enumerate(first_batch):
                p1, p2 = self._get_provider(model1["id"]), self._get_provider(model2["id"])
                provider_info.append(f"{p1} vs {p2}")
                
                # Track positions for spacing analysis
                for p in [p1, p2]:
                    if p not in provider_positions:
                        provider_positions[p] = []
                    provider_positions[p].append(i)
            
            # Calculate spacing stats
            spacing_stats = []
            for provider, positions in provider_positions.items():
                if len(positions) > 1:
                    spacings = [positions[i+1] - positions[i] for i in range(len(positions)-1)]
                    min_spacing = min(spacings)
                    spacing_stats.append(f"{provider}:{min_spacing}")
            
            logger.info(f"🎯 Found {len(sorted_pairs)} unplayed model pairs (optimized for {self.max_workers}-worker batching)")
            logger.info(f"📊 Next {batch_size} matches: {' | '.join(provider_info)}")
            if spacing_stats:
                logger.info(f"⏱️ Provider min spacings: {', '.join(spacing_stats)} (target: ≥{self.max_workers})")
        
        return sorted_pairs
    
    def _get_provider(self, model_id: str) -> str:
        """Extract provider from model ID (e.g., 'openai/gpt-4' -> 'openai')"""
        return model_id.split('/')[0] if '/' in model_id else model_id.split(':')[0]
    
    def _optimize_pair_ordering(self, pairs: List[Tuple[Dict, Dict, str, str]]) -> List[Tuple[Dict, Dict, str, str]]: 
        """
        Reorder pairs to maximize spacing between matches using the same provider across batches.
        This considers the full batch size (max_workers) to minimize concurrent provider usage.
        """
        if not pairs:
            return pairs
        
        # Group pairs by providers they use
        provider_usage = {}
        for i, (model1, model2, agent1_id, agent2_id) in enumerate(pairs):
            providers = {self._get_provider(model1["id"]), self._get_provider(model2["id"])}
            for provider in providers:
                if provider not in provider_usage:
                    provider_usage[provider] = []
                provider_usage[provider].append(i)
        
        # Use a more sophisticated scheduling algorithm
        return self._schedule_with_spacing(pairs, provider_usage)
    
    def _schedule_with_spacing(self, pairs: List[Tuple[Dict, Dict, str, str]], 
                              provider_usage: Dict[str, List[int]]) -> List[Tuple[Dict, Dict, str, str]]:
        """
        Schedule pairs to maximize spacing between same-provider usage.
        Uses a round-robin-like approach that tries to spread provider usage as evenly as possible.
        """
        scheduled = []
        used_indices = set()
        batch_size = self.max_workers
        
        # Track when each provider was last used (position in the scheduled list)
        provider_last_used = {}
        
        while len(scheduled) < len(pairs):
            available_pairs = [(i, pair) for i, pair in enumerate(pairs) if i not in used_indices]
            if not available_pairs:
                break
                
            # For each available pair, calculate a score based on provider spacing
            best_pair = None
            best_score = float('-inf')
            best_idx = -1
            
            for pair_idx, (model1, model2, agent1_id, agent2_id) in available_pairs:
                providers = {self._get_provider(model1["id"]), self._get_provider(model2["id"])}
                
                # Calculate spacing score for this pair
                score = self._calculate_spacing_score(providers, provider_last_used, len(scheduled), batch_size)
                
                if score > best_score:
                    best_score = score
                    best_pair = (model1, model2, agent1_id, agent2_id)
                    best_idx = pair_idx
            
            if best_pair:
                scheduled.append(best_pair)
                used_indices.add(best_idx)
                
                # Update last used positions for providers
                providers = {self._get_provider(best_pair[0]["id"]), self._get_provider(best_pair[1]["id"])}
                for provider in providers:
                    provider_last_used[provider] = len(scheduled) - 1
        
        return scheduled
    
    def _calculate_spacing_score(self, providers: set, provider_last_used: Dict[str, int], 
                                current_position: int, batch_size: int) -> float:
        """
        Calculate a score for placing a pair at the current position.
        Higher scores are better (more spacing).
        """
        if not providers:
            return 0
        
        total_score = 0
        for provider in providers:
            if provider not in provider_last_used:
                # First time using this provider - good
                total_score += 100
            else:
                last_pos = provider_last_used[provider]
                spacing = current_position - last_pos
                
                # Prefer spacing that's at least batch_size apart for true parallelism
                if spacing >= batch_size:
                    total_score += 50 + spacing  # Bonus for good spacing
                elif spacing >= batch_size // 2:
                    total_score += 25 + spacing  # Partial bonus
                else:
                    total_score += spacing  # Linear penalty for close spacing
        
        # Average across providers in this pair
        return total_score / len(providers)
    
    def create_llm_from_model(self, model: Dict) -> ChatOpenAI:
        """Create ChatOpenAI instance for a model"""
        return ChatOpenAI(
            model=model["id"],
            openai_api_base="https://openrouter.ai/api/v1",
            api_key=os.getenv("OPENROUTER_API_KEY"),
            temperature=0.0,
            timeout=25
        )
    
    def run_single_match_sync(self, model1: Dict, model2: Dict, agent1_id: str, agent2_id: str) -> bool:
        """Synchronous version of run_single_match for thread pool execution"""
        try:
            with self.lock:
                self.active_matches += 1
                logger.info(f"🎮 Starting match: {model1['name']} vs {model2['name']} (Active: {self.active_matches}/{self.max_workers})")
            
            # Create LLM instances
            llm1 = self.create_llm_from_model(model1)
            llm2 = self.create_llm_from_model(model2)
            
            # Run the match (convert async to sync using new event loop in thread)
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                match_result = loop.run_until_complete(play_match(llm1, llm2, max_turns=20))
            finally:
                loop.close()
            
            # Store results
            elo_changes = store_match_result(agent1_id, agent2_id, match_result)
            
            # Log defaults if any
            default_info = []
            if match_result.get('agent1_defaulted', False):
                default_info.append(f"{model1['name']} defaulted")
            if match_result.get('agent2_defaulted', False):
                default_info.append(f"{model2['name']} defaulted")
            
            default_text = f" ({', '.join(default_info)})" if default_info else ""
            
            logger.info(f"💾 Match completed - {model1['name']} ({elo_changes['old_elo1']}→{elo_changes['new_elo1']}) vs {model2['name']} ({elo_changes['old_elo2']}→{elo_changes['new_elo2']}){default_text}")
            logger.info(f"📊 Result: {match_result['result_text']}")
            
            with self.lock:
                self.active_matches -= 1
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Match failed: {model1['name']} vs {model2['name']} - {e}")

            with self.lock:
                self.active_matches -= 1
            return False
    
    async def run_single_match(self, model1: Dict, model2: Dict, agent1_id: str, agent2_id: str):
        """Async version of run_single_match for use within event loop"""
        try:
            with self.lock:
                self.active_matches += 1
                logger.info(f"🎮 Starting match: {model1['name']} vs {model2['name']} (Active: {self.active_matches}/{self.max_workers})")
            
            # Create LLM instances
            llm1 = self.create_llm_from_model(model1)
            llm2 = self.create_llm_from_model(model2)
            
            # Run the match (async)
            match_result = await play_match(llm1, llm2, max_turns=20)
            
            # Store results
            elo_changes = store_match_result(agent1_id, agent2_id, match_result)
            
            # Log defaults if any
            default_info = []
            if match_result.get('agent1_defaulted', False):
                default_info.append(f"{model1['name']} defaulted")
            if match_result.get('agent2_defaulted', False):
                default_info.append(f"{model2['name']} defaulted")
            
            default_text = f" ({', '.join(default_info)})" if default_info else ""
            
            logger.info(f"💾 Match completed - {model1['name']} ({elo_changes['old_elo1']}→{elo_changes['new_elo1']}) vs {model2['name']} ({elo_changes['old_elo2']}→{elo_changes['new_elo2']}){default_text}")
            logger.info(f"📊 Result: {match_result['result_text']}")
            
            with self.lock:
                self.active_matches -= 1
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Match failed: {model1['name']} vs {model2['name']} - {e}")
            with self.lock:
                self.active_matches -= 1
            return False
    
    async def run_matches(self, test_mode=False):
        """Main loop to run matches continuously"""
        create_tables()
        logger.info("📊 Database tables ensured")
        
        match_count = 0
        
        while not shutdown_requested:
            try:
                # Fetch current models
                models = get_models()
                if not models:
                    logger.warning("⚠️ No models available, exiting...")
                    return
                model_hash = set()
                text_models = []
                for model in models:
                    if model["id"].split(":")[0] in model_hash:
                        continue 
                    else:
                        if ("text" in model.get("architecture", {}).get("output_modalities", [])) and ("tools" in model.get("supported_parameters",[])):
                            model_hash.add(model["id"].split(":")[0])
                            text_models.append(model)
                
                if len(text_models) < 2:
                    logger.warning("⚠️ Need at least 2 text models, exiting...")
                    return 
                
                # Find unplayed pairs
                unplayed_pairs = self.find_unplayed_pairs(text_models)
                
                if not unplayed_pairs:
                    logger.info("🎉 All possible matches have been played!")
                    return 
                
                if test_mode:
                    # In test mode, run just one match
                    model1, model2, agent1_id, agent2_id = unplayed_pairs[0]
                    success = await self.run_single_match(model1, model2, agent1_id, agent2_id) # TODO: this method of match running is actually quite problematic, as the order in which matches played does matter, there needs to be matching based on number of matches played as well, this double for loop scheduling means the initial models get to play the most uncalibrated elo ratings, while later models do not, but this should self correct and only intially result in a skew. 
                    
                    if success:
                        match_count += 1
                        logger.info(f"✅ Completed match #{match_count}")
                        logger.info("🧪 Test mode: Completed one match, exiting...")
                        return
                else:
                    # In normal mode, run matches in parallel
                    # Submit matches up to max_workers
                    futures = []
                    pairs_to_run = unplayed_pairs[:self.max_workers]
                    
                    for model1, model2, agent1_id, agent2_id in pairs_to_run:
                        future = self.executor.submit(
                            self.run_single_match_sync, 
                            model1, model2, agent1_id, agent2_id
                        )
                        futures.append(future)
                    
                    # Wait for at least one match to complete
                    if futures:
                        completed_futures = as_completed(futures, timeout=600)  # 10 minute timeout per batch
                        for future in completed_futures:
                            try:
                                success = future.result()
                                if success:
                                    match_count += 1
                                    logger.info(f"✅ Completed match #{match_count}")
                            except Exception as e:
                                logger.error(f"❌ Future execution error: {e}")
                            
            except Exception as e:
                logger.error(f"❌ Error in main loop: {e}")
                if test_mode:
                    logger.error("🧪 Test mode: Error occurred, exiting...")
                    return
        
        # Cleanup
        self.executor.shutdown(wait=True)
        logger.info(f"🏁 Shutdown complete. Total matches run: {match_count}")


async def main(test_mode, max_workers):
    """Main entry point"""

    if test_mode:
        logger.info("🧪 Starting dilemma-bench match runner in TEST MODE (will run one match and exit)")
        max_workers = 1  # Force single thread in test mode
    else:
        logger.info(f"🚀 Starting dilemma-bench match runner with {max_workers} worker threads")
        logger.info("Press Ctrl+C to stop gracefully")
    
    runner = MatchRunner(max_workers=max_workers)
    await runner.run_matches(test_mode=test_mode)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
    description='dilemma-bench Match Runner',
    formatter_class=argparse.RawDescriptionHelpFormatter,
    epilog=textwrap.dedent('''
Examples:
python run_matches.py                    # Run continuously with 4 workers
python run_matches.py --test             # Test mode - run one match 
python run_matches.py --workers 8        # Run with 8 parallel workers
python run_matches.py --test --workers 1 # Test mode with single worker
    '''))
    parser.add_argument('--test', action='store_true',
                    help='Run in test mode (single match, then exit)')
    parser.add_argument('--workers', type=int, default=4,
                    help='Number of parallel worker threads (1-16, default: 4)')
    args = parser.parse_args()
    asyncio.run(main(args.test, args.workers))