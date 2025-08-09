'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { 
  apiClient, 
  UserProfile, 
  AgentProfile, 
  MatchHistoryEntry, 
  MatchTranscript 
} from '@/lib/api';
import { 
  User, 
  Bot, 
  Trophy, 
  Target, 
  Clock, 
  TrendingUp, 
  Eye,
  Calendar,
  Activity,
  AlertTriangle,
  Edit3,
  Save,
  X,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  ChevronLeft,
  ChevronRight
} from 'lucide-react';
import { Label, Pie, PieChart, Cell } from 'recharts';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { ChartConfig, ChartContainer, ChartTooltip, ChartTooltipContent } from '@/components/ui/chart';

interface User {
  id: string;
  email: string;
  name: string;
  picture: string;
  accessToken: string;
}

interface ProfilePageProps {
  profileId: string;
  profileType: 'user' | 'agent';
  user: User | null;
}

type Profile = UserProfile | AgentProfile;

type SortField = 'date' | 'opponent' | 'result';
type SortDirection = 'asc' | 'desc';

export default function ProfilePage({ profileId, profileType, user }: ProfilePageProps) {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [matchHistory, setMatchHistory] = useState<MatchHistoryEntry[]>([]);
  const [sortedMatches, setSortedMatches] = useState<MatchHistoryEntry[]>([]);
  const [sortField, setSortField] = useState<SortField>('date');
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc');
  const [matchPage, setMatchPage] = useState(1);
  const [resultFilter, setResultFilter] = useState<'wins' | 'losses' | 'draws' | null>(null);
  const [actionFilter, setActionFilter] = useState<'submit' | 'withhold' | 'default' | null>(null);
  const [matchIdToPlayerAction, setMatchIdToPlayerAction] = useState<Record<string, 'submit' | 'withhold' | 'default' | undefined>>({});
  const [loadingActions, setLoadingActions] = useState(false);
  
  const matchesPerPage = 10;
  const [selectedMatch, setSelectedMatch] = useState<MatchTranscript | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMatch, setLoadingMatch] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editingUsername, setEditingUsername] = useState(false);
  const [newUsername, setNewUsername] = useState('');

  const isOwnProfile = user?.id === profileId && profileType === 'user';

  useEffect(() => {
    const fetchProfile = async () => {
      setLoading(true);
      
      try {
        const profileResult = profileType === 'user' 
          ? await apiClient.getUserProfile(profileId)
          : await apiClient.getAgentProfile(profileId);
        
        if (profileResult.error) {
          setError(profileResult.error);
          return;
        }
        
        if (profileResult.data) {
          setProfile(profileResult.data);
          setNewUsername((profileResult.data as UserProfile).username || '');
        }

        // Fetch match history
        const historyResult = await apiClient.getMatchHistory(profileId);
        if (historyResult.data) {
          setMatchHistory(historyResult.data.matches);
        }
        
      } catch (err) {
        setError('Failed to load profile');
      } finally {
        setLoading(false);
      }
    };

    fetchProfile();
  }, [profileId, profileType]);

  // Helper: ensure we have player actions for matches when actionFilter is active
  useEffect(() => {
    const loadMissingActions = async () => {
      if (!actionFilter || !profile) return;
      const missing = matchHistory
        .filter((m) => matchIdToPlayerAction[m.id] === undefined)
        .map((m) => m.id);
      if (missing.length === 0) return;
      setLoadingActions(true);
      try {
        const results = await Promise.all(
          missing.map(async (id) => {
            const res = await apiClient.getMatchTranscript(id);
            return { id, data: res.data };
          })
        );
        setMatchIdToPlayerAction((prev) => {
          const next = { ...prev };
          for (const { id, data } of results) {
            if (!data) continue;
            const action = determinePlayerAction(data);
            next[id] = action === null ? undefined : action;
          }
          return next;
        });
      } finally {
        setLoadingActions(false);
      }
    };
    loadMissingActions();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [actionFilter, matchHistory, profile]);

  // Determine the profile player's action for a transcript
  const determinePlayerAction = (transcript: MatchTranscript): 'submit' | 'withhold' | 'default' | null => {
    if (!profile) return null;
    const ourName = (profile as any).name as string;
    const oppNames = new Set(matchHistory.map((m) => m.opponent_name));
    const a1 = transcript.agent1_name?.trim().toLowerCase();
    const a2 = transcript.agent2_name?.trim().toLowerCase();
    const me = ourName?.trim().toLowerCase();

    let isPlayer1: boolean | null = null;
    if (a1 && me && a1 === me) isPlayer1 = true;
    else if (a2 && me && a2 === me) isPlayer1 = false;
    else if (a1 && oppNames.has(transcript.agent1_name)) isPlayer1 = false;
    else if (a2 && oppNames.has(transcript.agent2_name)) isPlayer1 = true;

    if (isPlayer1 === null) return null;

    const defaulted = isPlayer1 ? transcript.agent1_default : transcript.agent2_default;
    if (defaulted) return 'default';

    const raw = (isPlayer1 ? transcript.agent1_action : transcript.agent2_action) || '';
    const v = raw.trim().toLowerCase();
    if (v.includes('submit')) return 'submit';
    if (v.includes('withhold')) return 'withhold';
    // Unknown action string, skip
    return null;
  };

  // Sort & filter matches whenever dependencies change
  useEffect(() => {
    let base = matchHistory;
    if (resultFilter) {
      base = base.filter((m) =>
        resultFilter === 'wins' ? m.result === 1 : resultFilter === 'losses' ? m.result === 2 : m.result === 0
      );
    }
    if (actionFilter) {
      base = base.filter((m) => matchIdToPlayerAction[m.id] === actionFilter);
    }

    const sorted = [...base].sort((a, b) => {
      let aValue: any;
      let bValue: any;

      switch (sortField) {
        case 'date':
          aValue = new Date(a.created_at).getTime();
          bValue = new Date(b.created_at).getTime();
          break;
        case 'opponent':
          aValue = a.opponent_name.toLowerCase();
          bValue = b.opponent_name.toLowerCase();
          break;
        case 'result':
          aValue = a.result;
          bValue = b.result;
          break;
        default:
          return 0;
      }

      if (aValue < bValue) return sortDirection === 'asc' ? -1 : 1;
      if (aValue > bValue) return sortDirection === 'asc' ? 1 : -1;
      return 0;
    });

    setSortedMatches(sorted);
  }, [matchHistory, sortField, sortDirection, resultFilter, actionFilter, matchIdToPlayerAction]);

  // Reset pagination when filter changes
  useEffect(() => {
    setMatchPage(1);
  }, [resultFilter, actionFilter]);

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc');
    } else {
      setSortField(field);
      setSortDirection(field === 'date' ? 'desc' : 'asc'); // Default to desc for date, asc for others
    }
  };

  const getSortIcon = (field: SortField) => {
    if (sortField !== field) {
      return <ArrowUpDown className="w-4 h-4 text-gray-400" />;
    }
    return sortDirection === 'asc' ? 
      <ArrowUp className="w-4 h-4 text-blue-500" /> : 
      <ArrowDown className="w-4 h-4 text-blue-500" />;
  };

  // Calculate pagination for matches
  const totalMatchPages = Math.ceil(sortedMatches.length / matchesPerPage);
  const matchStartIndex = (matchPage - 1) * matchesPerPage;
  const matchEndIndex = matchStartIndex + matchesPerPage;
  const currentMatches = sortedMatches.slice(matchStartIndex, matchEndIndex);

  const goToMatchPage = (page: number) => {
    setMatchPage(Math.max(1, Math.min(page, totalMatchPages)));
  };

  const handleMatchClick = async (matchId: string) => {
    setLoadingMatch(true);
    const result = await apiClient.getMatchTranscript(matchId);
    
    if (result.data) {
      setSelectedMatch(result.data);
    }
    
    setLoadingMatch(false);
  };

  const handleUsernameUpdate = async () => {
    if (!newUsername.trim() || !isOwnProfile || !user) return;
    
    const result = await apiClient.updateUsername(profileId, newUsername.trim(), user.accessToken);
    
    if (!result.error && profile) {
      setProfile({
        ...profile,
        username: newUsername.trim()
      } as UserProfile);
      setEditingUsername(false);
    }
  };

  const getResultText = (result: number) => {
    switch (result) {
      case 1: return 'Win';
      case 2: return 'Loss';
      case 0: return 'Draw';
      default: return 'Unknown';
    }
  };

  const getResultColor = (result: number) => {
    switch (result) {
      case 1: return 'text-green-600 bg-green-50';
      case 2: return 'text-red-600 bg-red-50';
      case 0: return 'text-yellow-600 bg-yellow-50';
      default: return 'text-gray-600 bg-gray-50';
    }
  };

  if (loading) {
    return (
      <div className="max-w-6xl mx-auto p-6">
        <div className="animate-pulse">
          <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 mb-6">
            <div className="flex items-center space-x-4">
              <div className="w-16 h-16 bg-gray-200 rounded-full"></div>
              <div className="flex-1">
                <div className="h-6 bg-gray-200 rounded w-1/3 mb-2"></div>
                <div className="h-4 bg-gray-200 rounded w-1/4"></div>
              </div>
            </div>
          </div>
          
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="bg-white rounded-lg shadow-sm border border-gray-200 p-4">
                <div className="h-4 bg-gray-200 rounded w-1/2 mb-2"></div>
                <div className="h-8 bg-gray-200 rounded w-3/4"></div>
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (error || !profile) {
    return (
      <div className="max-w-6xl mx-auto p-6">
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
          <div className="text-center py-12">
            <AlertTriangle className="w-12 h-12 text-red-500 mx-auto mb-4" />
            <h3 className="text-lg font-semibold text-gray-900 mb-2">Profile not found</h3>
            <p className="text-gray-600">{error || 'The requested profile could not be found.'}</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-6xl mx-auto p-6">
      {/* Profile Header */}
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 mb-6 mt-8">
        <div className="flex items-start justify-between">
          <div className="flex items-center space-x-4">
            <div className="w-16 h-16 bg-gradient-to-br from-blue-500 to-purple-600 rounded-full flex items-center justify-center">
              {profileType === 'user' ? (
                <User className="w-8 h-8 text-white" />
              ) : (
                <Bot className="w-8 h-8 text-white" />
              )}
            </div>
            
            <div>
              <h1 className="text-2xl font-bold text-gray-900">{profile.name}</h1>
              
              {profileType === 'user' && (
                <div className="flex items-center space-x-2 mt-1">
                  {editingUsername && isOwnProfile ? (
                    <div className="flex items-center space-x-2">
                      <input
                        type="text"
                        value={newUsername}
                        onChange={(e) => setNewUsername(e.target.value)}
                        className="px-2 py-1 text-sm border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
                        placeholder="Enter username"
                      />
                      <button
                        onClick={handleUsernameUpdate}
                        className="p-1 text-green-600 hover:bg-green-50 rounded"
                      >
                        <Save className="w-4 h-4" />
                      </button>
                      <button
                        onClick={() => {
                          setEditingUsername(false);
                          setNewUsername((profile as UserProfile).username || '');
                        }}
                        className="p-1 text-red-600 hover:bg-red-50 rounded"
                      >
                        <X className="w-4 h-4" />
                      </button>
                    </div>
                  ) : (
                    <div className="flex items-center space-x-2">
                      <span className="text-gray-600">@{(profile as UserProfile).username}</span>
                      {isOwnProfile && (
                        <button
                          onClick={() => setEditingUsername(true)}
                          className="p-1 text-gray-400 hover:text-blue-600 hover:bg-blue-50 rounded"
                        >
                          <Edit3 className="w-4 h-4" />
                        </button>
                      )}
                    </div>
                  )}
                </div>
              )}
              
              {profileType === 'agent' && (profile as AgentProfile).description && (
                <p className="text-gray-600 mt-1">{(profile as AgentProfile).description}</p>
              )}
              
              <div className="flex items-center space-x-2 mt-2 text-sm text-gray-500">
                <Calendar className="w-4 h-4" />
                <span>Joined {new Date(profile.created_at).toLocaleDateString()}</span>
                {profileType === 'user' && (profile as UserProfile).elo_history && (
                  <>
                    <span>•</span>
                    <span>{(profile as UserProfile).elo_history.length} ELO updates</span>
                  </>
                )}
              </div>
            </div>
          </div>
          
          <div className="text-right">
            <div className="text-3xl font-bold text-gray-900">{profile.elo}</div>
            <div className="text-sm text-gray-500 uppercase tracking-wide">ELO Rating</div>
          </div>
        </div>
      </div>

      {/* Condensed W/L/Rate Pie */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
        <Card className="flex flex-col">
          <CardHeader className="items-center pb-0">
            <CardTitle>Results Breakdown</CardTitle>
            <CardDescription>Wins / Losses / Draws</CardDescription>
          </CardHeader>
          <CardContent className="flex-1 pb-0">
            {(() => {
              const total = profile.total_matches || 0;
              const wins = profile.wins || 0;
              // Derive losses from total and wins and draws from result=0 in history later
              // Since profiles do not include draws, approximate losses as total - wins - draws
              const draws = matchHistory.filter(m => m.result === 0).length;
              const losses = Math.max(total - wins - draws, 0);

              const chartData = [
                { key: 'wins', label: 'Wins', value: wins, fill: 'var(--color-wins)', total },
                { key: 'losses', label: 'Losses ', value: losses, fill: 'var(--color-losses)', total },
                { key: 'draws', label: 'Draws ', value: draws, fill: 'var(--color-draws)', total },
              ];

              const chartConfig: ChartConfig = {
                value: { label: 'Matches' },
                wins: { label: 'Wins ', color: 'var(--chart-1)' },
                losses: { label: 'Losses ', color: 'var(--chart-2)' },
                draws: { label: 'Draws ', color: 'var(--chart-3)' },
              };

              return (
                <ChartContainer config={chartConfig} className="mx-auto aspect-square max-h-[250px]">
                  <PieChart>
                    <ChartTooltip
                      cursor={false}
                      content={
                        <ChartTooltipContent
                          hideLabel
                          formatter={(value, name, item: any) => {
                            const totalV = item?.payload?.total ?? 0;
                            const pct = totalV ? ((value as number) / totalV) * 100 : 0;
                            return (
                              <div className="flex w-full justify-between">
                                <span className="text-muted-foreground">{name}</span>
                                <span className="text-foreground font-mono font-medium tabular-nums">
                                  {(value as number).toLocaleString()} ({pct.toFixed(1)}%)
                                </span>
                              </div>
                            );
                          }}
                        />
                      }
                    />
                    <Pie data={chartData} dataKey="value" nameKey="label" innerRadius={60} strokeWidth={5}>
                      {chartData.map((entry) => (
                        <Cell
                          key={entry.key}
                          fill={entry.fill as string}
                          onClick={() =>
                            setResultFilter((prev) => (prev === entry.key ? null : (entry.key as 'wins' | 'losses' | 'draws')))
                          }
                          style={{ cursor: 'pointer' }}
                          opacity={resultFilter && resultFilter !== (entry.key as any) ? 0.4 : 1}
                        />
                      ))}
                      <Label
                        content={({ viewBox }) => {
                          if (viewBox && 'cx' in viewBox && 'cy' in viewBox) {
                            return (
                              <text x={viewBox.cx} y={viewBox.cy} textAnchor="middle" dominantBaseline="middle">
                                <tspan x={viewBox.cx} y={viewBox.cy} className="fill-foreground text-3xl font-bold">
                                  {total.toLocaleString()}
                                </tspan>
                                <tspan x={viewBox.cx} y={(viewBox.cy || 0) + 24} className="fill-muted-foreground">
                                  Matches
                                </tspan>
                              </text>
                            );
                          }
                        }}
                      />
                    </Pie>
                  </PieChart>
                </ChartContainer>
              );
            })()}
          </CardContent>
          <CardFooter className="flex-col gap-2 text-sm">
            <div className="text-muted-foreground leading-none">
              Win rate: <span className="font-semibold text-foreground">{(profile.win_rate * 100).toFixed(1)}%</span>
            </div>
          </CardFooter>
        </Card>
      
        {/* Action Distribution Donut */}
        <Card className="flex flex-col">
          <CardHeader className="items-center pb-0">
            <CardTitle>Action Distribution</CardTitle>
            <CardDescription>submit_evidence / withhold / default</CardDescription>
          </CardHeader>
          <CardContent className="flex-1 pb-0">
            {(() => {
              const submitCount = (profile as any).action_counts?.submit_evidence ?? 0;
              const withholdRaw = (profile as any).action_counts?.withhold ?? 0;
              const defaultCount = (profile as any).defaults ?? 0;
              const withholdCount = Math.max(withholdRaw - defaultCount, 0);
              const total = submitCount + withholdCount + defaultCount;

              const chartData = [
                { key: 'submit', label: 'submit_evidence ', value: submitCount, fill: 'var(--color-submit)', total },
                { key: 'withhold', label: 'withhold ', value: withholdCount, fill: 'var(--color-withhold)', total },
                { key: 'default', label: 'default (→ withhold) ', value: defaultCount, fill: 'var(--color-default)', total },
              ];

              const chartConfig: ChartConfig = {
                value: { label: 'Actions' },
                submit: { label: 'submit_evidence ', color: 'var(--chart-1)' },
                withhold: { label: 'withhold ', color: 'var(--chart-2)' },
                default: { label: 'default (→ withhold) ', color: 'var(--chart-3)' },
              };

              return (
                <ChartContainer config={chartConfig} className="mx-auto aspect-square max-h-[250px]">
                  <PieChart>
                    <ChartTooltip
                      cursor={false}
                      content={
                        <ChartTooltipContent
                          hideLabel
                          formatter={(value, name, item: any) => {
                            const totalV = item?.payload?.total ?? 0;
                            const pct = totalV ? ((value as number) / totalV) * 100 : 0;
                            return (
                              <div className="flex w-full justify-between">
                                <span className="text-muted-foreground">{name} </span>
                                <span className="text-foreground font-mono font-medium tabular-nums">
                                  {(value as number).toLocaleString()} ({pct.toFixed(1)}%)
                                </span>
                              </div>
                            );
                          }}
                        />
                      }
                    />
                    <Pie data={chartData} dataKey="value" nameKey="label" innerRadius={60} strokeWidth={5}>
                      {chartData.map((entry) => (
                        <Cell
                          key={entry.key}
                          fill={entry.fill as string}
                          onClick={() =>
                            setActionFilter((prev) => (prev === entry.key ? null : (entry.key as 'submit' | 'withhold' | 'default')))
                          }
                          style={{ cursor: 'pointer' }}
                          opacity={actionFilter && actionFilter !== (entry.key as any) ? 0.4 : 1}
                        />
                      ))}
                      <Label
                        content={({ viewBox }) => {
                          if (viewBox && 'cx' in viewBox && 'cy' in viewBox) {
                            return (
                              <text x={viewBox.cx} y={viewBox.cy} textAnchor="middle" dominantBaseline="middle">
                                <tspan x={viewBox.cx} y={viewBox.cy} className="fill-foreground text-3xl font-bold">
                                  {total.toLocaleString()}
                                </tspan>
                                <tspan x={viewBox.cx} y={(viewBox.cy || 0) + 24} className="fill-muted-foreground">
                                  Actions
                                </tspan>
                              </text>
                            );
                          }
                        }}
                      />
                    </Pie>
                  </PieChart>
                </ChartContainer>
              );
            })()}
          </CardContent>
          <CardFooter className="flex-col gap-2 text-sm">
            <div className="text-muted-foreground leading-none">
              Defaults count included but attributed to withhold for results.
            </div>
          </CardFooter>
        </Card>
      </div>


      {/* ELO History Chart (for users) */}
      {profileType === 'user' && (profile as UserProfile).elo_history && (
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 mb-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
            <TrendingUp className="w-5 h-5" />
            ELO History
          </h2>
          <div className="h-32 flex items-end space-x-1">
            {(profile as UserProfile).elo_history.map((elo, index) => {
              const maxElo = Math.max(...(profile as UserProfile).elo_history);
              const minElo = Math.min(...(profile as UserProfile).elo_history);
              const height = ((elo - minElo) / (maxElo - minElo)) * 100 || 50;
              
              return (
                <div
                  key={index}
                  className="bg-blue-500 rounded-t flex-1 min-h-[4px] transition-all hover:bg-blue-600"
                  style={{ height: `${height}%` }}
                  title={`Game ${index + 1}: ${elo} ELO`}
                />
              );
            })}
          </div>
        </div>
      )}

      {/* Match History */}
      <div className="bg-white rounded-lg shadow-sm border border-gray-200">
        <div className="px-6 py-4 border-b border-gray-200">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
              <Clock className="w-5 h-5" />
              {resultFilter || actionFilter ? (
                <>
                  Recent Matches ({sortedMatches.length} of {matchHistory.length})
                </>
              ) : (
                <>Recent Matches ({matchHistory.length})</>
              )}
            </h2>
            {(resultFilter || actionFilter) && (
              <div className="flex items-center gap-3">
                <span className="text-xs px-2 py-1 rounded-full bg-blue-50 text-blue-700 border border-blue-200">
                  Filtered by: {[
                    resultFilter ? resultFilter.charAt(0).toUpperCase() + resultFilter.slice(1) : null,
                    actionFilter ? (actionFilter === 'submit' ? 'Submit evidence' : actionFilter.charAt(0).toUpperCase() + actionFilter.slice(1)) : null,
                  ]
                    .filter(Boolean)
                    .join(' + ')}
                </span>
                {actionFilter && loadingActions && (
                  <span className="text-xs text-gray-500 flex items-center gap-1">
                    <Activity className="w-3 h-3 animate-spin" />
                    Loading actions...
                  </span>
                )}
                <button
                  onClick={() => {
                    setResultFilter(null);
                    setActionFilter(null);
                  }}
                  className="text-sm text-blue-600 hover:text-blue-700 px-3 py-1 rounded-md hover:bg-blue-50 border border-blue-200"
                >
                  Show all games
                </button>
              </div>
            )}
          </div>
        </div>
        
        {matchHistory.length === 0 ? (
          <div className="p-6">
            <div className="text-center py-8">
              <Clock className="w-12 h-12 text-gray-400 mx-auto mb-4" />
              <p className="text-gray-600">No matches played yet</p>
            </div>
          </div>
        ) : (
          <div className="overflow-hidden">
            {/* Sortable Headers */}
            <div className="bg-gray-50 px-6 py-3 border-b border-gray-200">
              <div className="grid grid-cols-12 gap-4 items-center text-sm font-medium text-gray-600">
                <div className="col-span-2">
                  <button
                    onClick={() => handleSort('result')}
                    className="flex items-center space-x-1 hover:text-gray-900 transition-colors"
                  >
                    <span>Result</span>
                    {getSortIcon('result')}
                  </button>
                </div>
                <div className="col-span-5">
                  <button
                    onClick={() => handleSort('opponent')}
                    className="flex items-center space-x-1 hover:text-gray-900 transition-colors"
                  >
                    <span>Opponent</span>
                    {getSortIcon('opponent')}
                  </button>
                </div>
                <div className="col-span-3">
                  <button
                    onClick={() => handleSort('date')}
                    className="flex items-center space-x-1 hover:text-gray-900 transition-colors"
                  >
                    <span>Date</span>
                    {getSortIcon('date')}
                  </button>
                </div>
                <div className="col-span-2 text-center">
                  <span>Actions</span>
                </div>
              </div>
            </div>

            {/* Match List */}
            <div className="px-6 py-2">
              {currentMatches.map((match, index) => (
                  <div
                    key={match.id}
                    className={`grid grid-cols-12 gap-4 items-center py-3 ${
                      index !== currentMatches.length - 1 ? 'border-b border-gray-100' : ''
                    } hover:bg-gray-50 transition-colors`}
                  >
                    <div className="col-span-2">
                      <div className={`inline-flex px-2 py-1 rounded text-sm font-medium ${getResultColor(match.result)}`}>
                        {getResultText(match.result)}
                      </div>
                    </div>
                    
                    <div className="col-span-5">
                      <div className="flex items-center space-x-2">
                        {match.opponent_type === 'user' ? (
                          <User className="w-4 h-4 text-blue-500 flex-shrink-0" />
                        ) : (
                          <Bot className="w-4 h-4 text-green-500 flex-shrink-0" />
                        )}
                        <span className="font-medium text-gray-900 truncate">
                          {match.opponent_name}
                        </span>
                        <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${
                          match.opponent_type === 'user' 
                            ? 'bg-blue-100 text-blue-700' 
                            : 'bg-green-100 text-green-700'
                        }`}>
                          {match.opponent_type === 'user' ? 'User' : 'LLM'}
                        </span>
                      </div>
                    </div>
                    
                    <div className="col-span-3">
                      <div className="text-sm text-gray-600">
                        <div>{new Date(match.created_at).toLocaleDateString()}</div>
                        <div className="text-xs text-gray-400">
                          {new Date(match.created_at).toLocaleTimeString()}
                        </div>
                      </div>
                    </div>
                    
                    <div className="col-span-2 text-center">
                      <button
                        onClick={() => handleMatchClick(match.id)}
                        className="inline-flex items-center space-x-1 text-blue-600 hover:text-blue-700 px-2 py-1 rounded-md hover:bg-blue-50 transition-colors text-sm"
                        disabled={loadingMatch}
                      >
                        <Eye className="w-4 h-4" />
                        <span>View</span>
                      </button>
                    </div>
                  </div>
                ))}
            </div>

            {/* Pagination */}
            {totalMatchPages > 1 && (
              <div className="px-6 py-4 border-t border-gray-200 bg-gray-50">
                <div className="flex items-center justify-between">
                  <div className="text-sm text-gray-600">
                    Showing {matchStartIndex + 1} to {Math.min(matchEndIndex, sortedMatches.length)} of {sortedMatches.length} matches
                  </div>
                  
                  <div className="flex items-center space-x-2">
                    <button
                      onClick={() => goToMatchPage(matchPage - 1)}
                      disabled={matchPage === 1}
                      className="p-2 rounded-md border border-gray-300 bg-white text-gray-500 hover:text-gray-700 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      <ChevronLeft className="w-4 h-4" />
                    </button>
                    
                    <div className="flex space-x-1">
                      {Array.from({ length: Math.min(5, totalMatchPages) }, (_, i) => {
                        let pageNum;
                        if (totalMatchPages <= 5) {
                          pageNum = i + 1;
                        } else if (matchPage <= 3) {
                          pageNum = i + 1;
                        } else if (matchPage >= totalMatchPages - 2) {
                          pageNum = totalMatchPages - 4 + i;
                        } else {
                          pageNum = matchPage - 2 + i;
                        }
                        
                        return (
                          <button
                            key={pageNum}
                            onClick={() => goToMatchPage(pageNum)}
                            className={`px-3 py-1 rounded-md text-sm font-medium ${
                              matchPage === pageNum
                                ? 'bg-blue-600 text-white'
                                : 'bg-white border border-gray-300 text-gray-700 hover:bg-gray-50'
                            }`}
                          >
                            {pageNum}
                          </button>
                        );
                      })}
                    </div>
                    
                    <button
                      onClick={() => goToMatchPage(matchPage + 1)}
                      disabled={matchPage === totalMatchPages}
                      className="p-2 rounded-md border border-gray-300 bg-white text-gray-500 hover:text-gray-700 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      <ChevronRight className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              </div>
            )}

            {/* Footer with match count */}
            {matchHistory.length > 0 && (
              <div className="px-6 py-3 bg-gray-50 border-t border-gray-200 text-sm text-gray-600">
                Total: {sortedMatches.length} matches played
              </div>
            )}
          </div>
        )}
      </div>

      {/* Match Transcript Modal */}
      {selectedMatch && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
          <div className="bg-white rounded-lg max-w-4xl w-full max-h-[80vh] overflow-hidden">
            <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
              <h3 className="text-lg font-semibold text-gray-900">
                {selectedMatch.agent1_name} vs {selectedMatch.agent2_name}
              </h3>
              <button
                onClick={() => setSelectedMatch(null)}
                className="p-2 text-gray-400 hover:text-gray-600 rounded-md hover:bg-gray-100"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            
            <div className="flex flex-col max-h-[60vh]">
              {/* Match Info Header */}
              <div className="px-6 py-3 bg-gray-50 border-b border-gray-200">
                <div className="grid grid-cols-3 gap-4 text-sm">
                  <div className="text-center">
                    <div className="font-medium text-gray-900">{selectedMatch.agent1_name}</div>
                    <div className="text-xs text-gray-500">Player 1</div>
                  </div>
                  <div className="text-center">
                    <div className="font-medium text-gray-600">vs</div>
                    <div className="text-xs text-gray-500">
                      {new Date(selectedMatch.created_at).toLocaleDateString()}
                    </div>
                  </div>
                  <div className="text-center">
                    <div className="font-medium text-gray-900">{selectedMatch.agent2_name}</div>
                    <div className="text-xs text-gray-500">Player 2</div>
                  </div>
                </div>
              </div>

              {/* Scrollable Transcript */}
              <div className="flex-1 overflow-y-auto p-6">
                <div className="space-y-4">
                  {selectedMatch.transcript.map((entry) => (
                    <div key={entry.order} className={`border-l-4 pl-4 ${
                      entry.agent_id === 0 ? 'border-gray-300' : 
                      entry.agent_id === 1 ? 'border-blue-300' : 'border-green-300'
                    }`}>
                      <div className="flex items-center justify-between mb-1">
                        <span className={`font-medium text-sm ${
                          entry.agent_id === 0 ? 'text-gray-600' : 
                          entry.agent_id === 1 ? 'text-blue-600' : 'text-green-600'
                        }`}>
                          {entry.agent_id === 0 ? 'System' : entry.agent_id === 1 ? selectedMatch.agent1_name : selectedMatch.agent2_name}
                        </span>
                        <span className="text-xs text-gray-400">
                          {new Date(entry.created_at).toLocaleTimeString()}
                        </span>
                      </div>
                      <div className={`p-3 rounded-lg ${
                        entry.agent_id === 0 ? 'bg-gray-50' : 
                        entry.agent_id === 1 ? 'bg-blue-50' : 'bg-green-50'
                      }`}>
                        <p className="text-gray-800 whitespace-pre-wrap">{entry.message}</p>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Match Result Footer */}
              <div className="px-6 py-3 bg-gray-50 border-t border-gray-200">
                <div className="flex items-center justify-center space-x-8 text-sm">
                  <div className="text-center">
                    <div className="font-medium text-gray-600">Result</div>
                    <div className={`font-bold ${
                      selectedMatch.result === 1 ? 'text-green-600' : 
                      selectedMatch.result === 2 ? 'text-red-600' : 'text-yellow-600'
                    }`}>
                      {selectedMatch.result === 1 ? `${selectedMatch.agent1_name} Wins` : 
                       selectedMatch.result === 2 ? `${selectedMatch.agent2_name} Wins` : 'Draw'}
                    </div>
                  </div>
                  {(selectedMatch.agent1_default || selectedMatch.agent2_default) && (
                    <div className="text-center">
                      <div className="font-medium text-orange-600">Defaults</div>
                      <div className="text-xs text-orange-500">
                        {selectedMatch.agent1_default && `${selectedMatch.agent1_name} `}
                        {selectedMatch.agent2_default && `${selectedMatch.agent2_name}`}
                      </div>
                    </div>
                  )}
                </div>
              </div>
              {/* Action Summary */}
              <div className="px-6 py-3 bg-gray-50 border-t border-gray-200">
                <div className="flex items-center justify-center gap-6 text-sm text-gray-700">
                  <div>
                    {selectedMatch.agent1_name}: <span className="font-medium">{selectedMatch.agent1_action}</span>
                  </div>
                  <div>
                    {selectedMatch.agent2_name}: <span className="font-medium">{selectedMatch.agent2_action}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}