'use client';


import { useEffect, useState } from 'react';
import { apiClient, MatchmakingStatus, GameSession } from '@/lib/api';
import { 
  Play, 
  Users, 
  Bot, 
  Clock, 
  Target, 
  LogIn,
  AlertCircle,
  CheckCircle,
  XCircle,
  Handshake,
  Swords,
  Info
} from 'lucide-react';

interface User {
  id: string;
  email: string;
  name: string;
  picture: string;
  accessToken: string;
}

interface GameInterfaceProps {
  user: User | null;
}

export default function GameInterface({ user }: GameInterfaceProps) {
  const [matchmakingStatus, setMatchmakingStatus] = useState<MatchmakingStatus | null>(null);
  const [currentGame, setCurrentGame] = useState<GameSession | null>(null);
  const [gameAction, setGameAction] = useState<'cooperate' | 'defect' | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!user) {
      return;
    }

    checkMatchmakingStatus();
    
    // Poll for updates every 2 seconds
    const interval = setInterval(checkMatchmakingStatus, 2000); //TODO: wow, change this 
    return () => clearInterval(interval);
  }, [user]);

  const checkMatchmakingStatus = async () => {
    if (!user) return;
    
    const result = await apiClient.getMatchmakingStatus(user.accessToken);
    if (result.data) {
      setMatchmakingStatus(result.data);
      
      // If there's an active game, fetch its details
      if (result.data.active_game) {
        const gameResult = await apiClient.getGameStatus(result.data.active_game, user.accessToken);
        if (gameResult.data) {
          setCurrentGame(gameResult.data);
        }
      } else {
        setCurrentGame(null);
      }
    }
  };

  const startGameVsLLM = async () => {
    if (!user) return;
    
    setLoading(true);
    setError(null);
    
    const result = await apiClient.startGameVsLLM(user.accessToken);
    
    if (result.error) {
      setError(result.error);
    } else if (result.data) {
      // Game created, poll for updates
      checkMatchmakingStatus();
    }
    
    setLoading(false);
  };

  const joinQueue = async () => {
    if (!user) return;
    
    setLoading(true);
    setError(null);
    
    const result = await apiClient.joinMatchmakingQueue(user.accessToken);
    
    if (result.error) {
      setError(result.error);
    } else {
      checkMatchmakingStatus();
    }
    
    setLoading(false);
  };

  const leaveQueue = async () => {
    if (!user) return;
    
    setLoading(true);
    
    const result = await apiClient.leaveMatchmakingQueue(user.accessToken);
    
    if (!result.error) {
      checkMatchmakingStatus();
    }
    
    setLoading(false);
  };

  const submitAction = async (action: 'cooperate' | 'defect') => {
    if (!currentGame || !user) return;
    
    setGameAction(action);
    setLoading(true);
    
    const result = await apiClient.submitGameAction(currentGame.game_id, action, user.accessToken);
    
    if (result.error) {
      setError(result.error);
      setGameAction(null);
    }
    
    setLoading(false);
  };



  if (!user) {
    return (
      <div className="max-w-4xl mx-auto p-6">
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
          <div className="text-center py-12">
            <LogIn className="w-12 h-12 text-blue-500 mx-auto mb-4" />
            <h3 className="text-lg font-semibold text-gray-900 mb-2">Login Required</h3>
            <p className="text-gray-600 mb-6">You need to be logged in to play a game. </p>
            <div className="border-t border-gray-200 dark:border-gray-600 pt-4 space-y-3 text-sm text-gray-600 dark:text-gray-400 my-4 ">
              <p>
                <strong>Your privacy:</strong> No selling data to third parties ever. No emails.
              </p>
              
              <p>
                <strong>Want out?</strong> You can delete your account anytime just email <a href="mailto:support@critique-labs.ai" className="text-blue-600 hover:text-blue-700 underline">support@critique-labs.ai</a>. 
                No hoops to jump through, just gone.
              </p>
            </div>
            <a
              href="/api/auth/login"
              className="inline-flex items-center space-x-2 bg-blue-600 text-white px-6 py-3 rounded-md hover:bg-blue-700 transition-colors"
            >
              <LogIn className="w-5 h-5" />
              <span>Login to Play</span>
            </a>
          </div>
        </div>
      </div>
    );
  }

  // If there's an active game, show the game interface
  if (currentGame) {
    const hasSubmittedAction = gameAction !== null;
    const gameComplete = currentGame.player1_action && currentGame.player2_action;
    
    return (
      <div className="max-w-4xl mx-auto p-6">
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
          <div className="text-center mb-8">
            <h1 className="text-2xl font-bold text-gray-900 mb-2">Prisoner's Dilemma</h1>
            <p className="text-gray-600">
              You are playing against {currentGame.player2_type === 'agent' ? 'an LLM agent' : 'another player'}
            </p>
          </div>

          {/* Game Status */}
          <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-6">
            <div className="flex items-center justify-center space-x-2">
              {hasSubmittedAction ? (
                <>
                  <CheckCircle className="w-5 h-5 text-green-500" />
                  <span className="text-green-700 font-medium">
                    Action submitted: {gameAction === 'cooperate' ? 'Cooperate' : 'Defect'}
                  </span>
                </>
              ) : (
                <>
                  <Clock className="w-5 h-5 text-blue-500" />
                  <span className="text-blue-700 font-medium">Waiting for your decision...</span>
                </>
              )}
            </div>
          </div>

          {/* Research Context */}
          <div className="border border-gray-200 rounded-lg p-4 mb-4">
            <div className="flex items-start gap-3">
              <div className="flex h-6 w-6 items-center justify-center rounded-full bg-blue-100">
                <Info className="h-4 w-4 text-blue-600" />
              </div>
              <div>
                <p className="text-sm text-gray-700">
                  <strong className="text-gray-900">Alignment research:</strong> This contributes to <a href="https://critique-labs.ai" target="_blank" rel="noopener noreferrer" className="underline text-blue-600 hover:text-blue-700">Critique AI</a>
                  — benchmarking how agents cooperate, compete, and adapt.
                </p>
              </div>
            </div>
          </div>

          {/* Game Rules */}
          <div className="bg-gray-50 rounded-lg p-6 mb-6">
            <h3 className="text-lg font-semibold text-gray-900 mb-4">Game Rules</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
              <div className="space-y-2">
                <div className="flex items-center space-x-2">
                  <Handshake className="w-4 h-4 text-green-500" />
                  <span><strong>Both Cooperate:</strong> Both get +3 points</span>
                </div>
                <div className="flex items-center space-x-2">
                  <Swords className="w-4 h-4 text-red-500" />
                  <span><strong>Both Defect:</strong> Both get +1 point</span>
                </div>
              </div>
              <div className="space-y-2">
                <div className="flex items-center space-x-2">
                  <Target className="w-4 h-4 text-orange-500" />
                  <span><strong>One Defects:</strong> Defector gets +5, Cooperator gets 0</span>
                </div>
                <div className="flex items-center space-x-2">
                  <AlertCircle className="w-4 h-4 text-blue-500" />
                  <span><strong>Goal:</strong> Maximize your score</span>
                </div>
              </div>
            </div>
          </div>

          {/* Action Buttons */}
          {!hasSubmittedAction && !gameComplete && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <button
                onClick={() => submitAction('cooperate')}
                disabled={loading}
                className="flex flex-col items-center justify-center p-8 border-2 border-green-300 rounded-lg hover:border-green-400 hover:bg-green-50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <Handshake className="w-12 h-12 text-green-500 mb-4" />
                <span className="text-xl font-semibold text-green-700">Cooperate</span>
                <span className="text-sm text-green-600 mt-2">Work together for mutual benefit</span>
              </button>

              <button
                onClick={() => submitAction('defect')}
                disabled={loading}
                className="flex flex-col items-center justify-center p-8 border-2 border-red-300 rounded-lg hover:border-red-400 hover:bg-red-50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <Swords className="w-12 h-12 text-red-500 mb-4" />
                <span className="text-xl font-semibold text-red-700">Defect</span>
                <span className="text-sm text-red-600 mt-2">Maximize your own gain</span>
              </button>
            </div>
          )}

          {/* Waiting for opponent */}
          {hasSubmittedAction && !gameComplete && (
            <div className="text-center py-8">
              <Clock className="w-12 h-12 text-blue-500 mx-auto mb-4 animate-spin" />
              <p className="text-gray-600">Waiting for opponent to make their decision...</p>
            </div>
          )}

          {/* Game Results */}
          {gameComplete && (
            <div className="bg-gray-50 rounded-lg p-6 text-center">
              <h3 className="text-lg font-semibold text-gray-900 mb-4">Game Complete!</h3>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
                 <div className="bg-white rounded-lg p-4">
                  <p className="font-medium">Your Action</p>
                  <p className="text-lg font-bold">
                     {currentGame.player1_action === 'cooperate' ? 'Cooperate' : 'Defect'}
                  </p>
                </div>
                 <div className="bg-white rounded-lg p-4">
                  <p className="font-medium">Opponent's Action</p>
                  <p className="text-lg font-bold">
                     {currentGame.player2_action === 'cooperate' ? 'Cooperate' : 'Defect'}
                  </p>
                </div>
              </div>
              <button
                onClick={() => {
                  setCurrentGame(null);
                  setGameAction(null);
                  checkMatchmakingStatus();
                }}
                className="bg-blue-600 text-white px-6 py-2 rounded-md hover:bg-blue-700 transition-colors"
              >
                Play Again
              </button>
            </div>
          )}

          {error && (
            <div className="mt-4 bg-red-50 border border-red-200 rounded-lg p-4">
              <div className="flex items-center space-x-2">
                <XCircle className="w-5 h-5 text-red-500" />
                <span className="text-red-700">{error}</span>
              </div>
            </div>
          )}
        </div>
      </div>
    );
  }

  // Main game selection interface
  return (
    <div className="max-w-4xl mx-auto p-6">
      {/* Game Explanation */}
      <div className="bg-gradient-to-r from-green-50 to-blue-50 rounded-lg border border-green-200 p-6 mb-6">
        <h1 className="text-2xl font-bold text-gray-900 mb-3">The Prisoner's Dilemma Challenge</h1>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div>
            <h3 className="font-semibold text-gray-900 mb-2">🎮 How It Works</h3>
            <p className="text-sm text-gray-700 mb-3">
              You and an opponent must independently choose to either <strong>Cooperate</strong> or <strong>Defect</strong> 
              without knowing the other's choice. Your payoff depends on both decisions.
            </p>
            <div className="bg-white rounded border p-3">
              <div className="grid grid-cols-2 gap-2 text-xs">
                <div className="font-medium text-center">Your Choice → Payoff</div>
                <div className="font-medium text-center">Opponent's Choice</div>
                <div className="text-green-600">Both Cooperate → +3</div>
                <div className="text-green-600">Both Cooperate → +3</div>
                <div className="text-red-600">You Defect → +5</div>
                <div className="text-gray-600">They Cooperate → 0</div>
                <div className="text-gray-600">You Cooperate → 0</div>
                <div className="text-red-600">They Defect → +5</div>
                <div className="text-orange-600">Both Defect → +1</div>
                <div className="text-orange-600">Both Defect → +1</div>
              </div>
            </div>
          </div>
          
          <div>
            <h3 className="font-semibold text-gray-900 mb-2">🧠 Research Purpose</h3>
            <p className="text-sm text-gray-700 mb-3">
              This benchmark tests strategic reasoning, cooperation tendencies, and communication skills in both 
              AI systems and humans. Part of <a href="https://critique-labs.ai" target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:text-blue-700 underline">Critique AI's</a> alignment research.
            </p>
            <div className="space-y-2">
              <div className="flex items-center text-sm text-gray-600">
                <span className="w-2 h-2 bg-blue-500 rounded-full mr-2"></span>
                All matches are blind - opponent revealed after
              </div>
              <div className="flex items-center text-sm text-gray-600">
                <span className="w-2 h-2 bg-green-500 rounded-full mr-2"></span>
                Results contribute to alignment research
              </div>
              <div className="flex items-center text-sm text-gray-600">
                <span className="w-2 h-2 bg-purple-500 rounded-full mr-2"></span>
                ELO ratings track performance over time
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
        <div className="text-center mb-8">
          <h2 className="text-2xl font-bold text-gray-900 mb-2">Choose Your Challenge</h2>
          <p className="text-gray-600">
            Test your strategic thinking against AI or human opponents
          </p>
        </div>

        {/* Matchmaking Status */}
        {matchmakingStatus?.in_queue && (
          <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4 mb-6">
            <div className="flex items-center justify-between">
              <div className="flex items-center space-x-2">
                <Clock className="w-5 h-5 text-yellow-500 animate-spin" />
                <span className="text-yellow-700 font-medium">
                  In matchmaking queue ({matchmakingStatus.queue_size} player{matchmakingStatus.queue_size !== 1 ? 's' : ''})
                </span>
              </div>
              <button
                onClick={leaveQueue}
                disabled={loading}
                className="text-red-600 hover:text-red-700 px-3 py-1 rounded-md hover:bg-red-50 transition-colors"
              >
                Leave Queue
              </button>
            </div>
          </div>
        )}

        {/* Game Options */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* Play vs LLM */}
          <div className="border border-gray-200 rounded-lg p-6 hover:border-gray-300 transition-colors">
            <div className="text-center">
              <div className="w-16 h-16 bg-green-100 rounded-full flex items-center justify-center mx-auto mb-4">
                <Bot className="w-8 h-8 text-green-600" />
              </div>
              <h3 className="text-xl font-semibold text-gray-900 mb-2">Play vs LLM</h3>
              <p className="text-gray-600 mb-6">
                Challenge a random AI agent. Games start immediately and are blind - you won't know which model you're facing until after.
              </p>
              <button
                onClick={startGameVsLLM}
                disabled={loading || matchmakingStatus?.in_queue}
                className="w-full bg-green-600 text-white py-3 px-4 rounded-md hover:bg-green-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center space-x-2"
              >
                <Play className="w-5 h-5" />
                <span>{loading ? 'Starting...' : 'Start Game'}</span>
              </button>
            </div>
          </div>

          {/* Play vs Human */}
          <div className="border border-gray-200 rounded-lg p-6 hover:border-gray-300 transition-colors">
            <div className="text-center">
              <div className="w-16 h-16 bg-blue-100 rounded-full flex items-center justify-center mx-auto mb-4">
                <Users className="w-8 h-8 text-blue-600" />
              </div>
              <h3 className="text-xl font-semibold text-gray-900 mb-2">Play vs Human</h3>
              <p className="text-gray-600 mb-6">
                Join the matchmaking queue to play against another human player. Games are also blind.
              </p>
              {matchmakingStatus?.in_queue ? (
                <button
                  onClick={leaveQueue}
                  disabled={loading}
                  className="w-full bg-red-600 text-white py-3 px-4 rounded-md hover:bg-red-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center space-x-2"
                >
                  <XCircle className="w-5 h-5" />
                  <span>Leave Queue</span>
                </button>
              ) : (
                <button
                  onClick={joinQueue}
                  disabled={loading}
                  className="w-full bg-blue-600 text-white py-3 px-4 rounded-md hover:bg-blue-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center space-x-2"
                >
                  <Users className="w-5 h-5" />
                  <span>{loading ? 'Joining...' : 'Join Queue'}</span>
                </button>
              )}
            </div>
          </div>
        </div>

        {/* Queue Status */}
        {matchmakingStatus && !matchmakingStatus.in_queue && matchmakingStatus.queue_size > 0 && (
          <div className="mt-6 text-center text-sm text-gray-600">
            {matchmakingStatus.queue_size} player{matchmakingStatus.queue_size !== 1 ? 's' : ''} currently in queue
          </div>
        )}

        {error && (
          <div className="mt-6 bg-red-50 border border-red-200 rounded-lg p-4">
            <div className="flex items-center space-x-2">
              <XCircle className="w-5 h-5 text-red-500" />
              <span className="text-red-700">{error}</span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}