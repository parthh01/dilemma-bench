// Access tokens will be passed as parameters instead of retrieved here

const BACKEND_BASE_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000';

interface ApiResponse<T> {
  data?: T;
  error?: string;
}

interface LeaderboardEntry {
  id: string;
  name: string;
  username?: string;
  elo: number;
  type: 'user' | 'agent';
  created_at: string;
  total_matches: number;
}

interface UserProfile {
  id: string;
  name: string;
  username: string;
  elo: number;
  elo_history: number[];
  created_at: string;
  total_matches: number;
  wins: number;
  win_rate: number;
  defaults: number;
  default_rate: number;
  action_counts: { withhold: number; submit_evidence: number };
  action_percentages: { withhold: number; submit_evidence: number };
}

interface AgentProfile {
  id: string;
  name: string;
  description: string;
  elo: number;
  created_at: string;
  updated_at: string;
  total_matches: number;
  wins: number;
  win_rate: number;
  defaults: number;
  default_rate: number;
  action_counts: { withhold: number; submit_evidence: number };
  action_percentages: { withhold: number; submit_evidence: number };
}

interface MatchHistoryEntry {
  id: string;
  opponent_id: string;
  opponent_name: string;
  opponent_type: 'user' | 'agent';
  result: number; // 1: win, 2: loss, 0: draw
  created_at: string;
}

interface MatchTranscript {
  match_id: string;
  agent1_name: string;
  agent2_name: string;
  result: number;
  agent1_default: boolean;
  agent2_default: boolean;
   agent1_action: string;
   agent2_action: string;
  created_at: string;
  transcript: Array<{
    order: number;
    agent_id: number;
    message: string;
    created_at: string;
  }>;
}

interface GameSession {
  game_id: string;
  player1_id: string;
  player1_type: string;
  player2_id: string;
  player2_type: string;
  status: string;
  created_at: number;
  player1_action?: string;
  player2_action?: string;
}

interface MatchmakingStatus {
  in_queue: boolean;
  queue_size: number;
  active_game: string | null;
}

class ApiClient {
  private async makeRequest<T>(
    endpoint: string,
    options: RequestInit = {}
  ): Promise<ApiResponse<T>> {
    try {
      const headers = new Headers(options.headers);
      headers.set('Content-Type', 'application/json');

      const response = await fetch(`/api/query-backend?endpoint=${encodeURIComponent(endpoint)}`, {
        ...options,
        headers,
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ error: 'Unknown error' }));
        return { error: errorData.error || `HTTP ${response.status}` };
      }

      const data = await response.json();
      return { data };
    } catch (error) {
      console.error('API request failed:', error);
      return { error: 'Network error' };
    }
  }

  private async makeAuthenticatedRequest<T>(
    endpoint: string,
    accessToken: string,
    options: RequestInit = {}
  ): Promise<ApiResponse<T>> {
    try {
      const headers = new Headers(options.headers);
      headers.set('Content-Type', 'application/json');
      if (accessToken) {
        headers.set('Authorization', `Bearer ${accessToken}`);
      }

      return this.makeRequest<T>(endpoint, {
        ...options,
        headers,
      });
    } catch (error) {
      console.error('Authenticated API request failed:', error);
      return { error: 'Authentication error' };
    }
  }

  // Public endpoints
  async getLeaderboard(): Promise<ApiResponse<{ leaderboard: LeaderboardEntry[] }>> {
    return this.makeRequest('/api/leaderboard');
  }

  async getUserProfile(userId: string): Promise<ApiResponse<UserProfile>> {
    return this.makeRequest(`/api/users/${userId}`);
  }

  async getAgentProfile(agentId: string): Promise<ApiResponse<AgentProfile>> {
    return this.makeRequest(`/api/agents/${agentId}`);
  }

  async getMatchHistory(playerId: string, limit: number = 50): Promise<ApiResponse<{ matches: MatchHistoryEntry[] }>> {
    return this.makeRequest(`/api/matches/history/${playerId}?limit=${limit}`);
  }

  async getMatchTranscript(matchId: string): Promise<ApiResponse<MatchTranscript>> {
    return this.makeRequest(`/api/matches/${matchId}/transcript`);
  }

  async getSystemPrompt(): Promise<ApiResponse<{ system_prompt: string }>> {
    return this.makeRequest('/api/system-prompt');
  }

  // Authenticated endpoints
  async getCurrentUser(accessToken: string): Promise<ApiResponse<UserProfile>> {
    return this.makeAuthenticatedRequest('/api/me', accessToken);
  }

  async updateUsername(userId: string, username: string, accessToken: string): Promise<ApiResponse<{ message: string }>> {
    return this.makeAuthenticatedRequest(`/api/users/${userId}/username`, accessToken, {
      method: 'PUT',
      body: JSON.stringify({ username }),
    });
  }

  async joinMatchmakingQueue(accessToken: string): Promise<ApiResponse<{ message: string; queue_position: number }>> {
    return this.makeAuthenticatedRequest('/api/matchmaking/queue', accessToken, {
      method: 'POST',
    });
  }

  async leaveMatchmakingQueue(accessToken: string): Promise<ApiResponse<{ message: string }>> {
    return this.makeAuthenticatedRequest('/api/matchmaking/queue', accessToken, {
      method: 'DELETE',
    });
  }

  async getMatchmakingStatus(accessToken: string): Promise<ApiResponse<MatchmakingStatus>> {
    return this.makeAuthenticatedRequest('/api/matchmaking/status', accessToken);
  }

  async startGameVsLLM(accessToken: string): Promise<ApiResponse<{ game_id: string; message: string; opponent_type: string }>> {
    return this.makeAuthenticatedRequest('/api/games/vs-llm', accessToken, {
      method: 'POST',
    });
  }

  async getGameStatus(gameId: string, accessToken: string): Promise<ApiResponse<GameSession>> {
    return this.makeAuthenticatedRequest(`/api/games/${gameId}`, accessToken);
  }

  async submitGameAction(gameId: string, action: 'cooperate' | 'defect', accessToken: string): Promise<ApiResponse<{ message: string }>> {
    return this.makeAuthenticatedRequest(`/api/games/${gameId}/action`, accessToken, {
      method: 'POST',
      body: JSON.stringify({ action }),
    });
  }
}

export const apiClient = new ApiClient();

export type {
  LeaderboardEntry,
  UserProfile,
  AgentProfile,
  MatchHistoryEntry,
  MatchTranscript,
  GameSession,
  MatchmakingStatus,
};