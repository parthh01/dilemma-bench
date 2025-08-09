'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { apiClient, LeaderboardEntry } from '@/lib/api';
import { Trophy, Medal, Award, User, Bot, Zap, ChevronLeft, ChevronRight, Info, CheckCircle } from 'lucide-react';


interface LeaderboardPageProps {}

export default function LeaderboardPage({}: LeaderboardPageProps) {
  const [leaderboard, setLeaderboard] = useState<LeaderboardEntry[]>([]);
  const [filteredLeaderboard, setFilteredLeaderboard] = useState<LeaderboardEntry[]>([]);
  const [currentPage, setCurrentPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  
  const itemsPerPage = 10;

  useEffect(() => {
    const fetchLeaderboard = async () => {
      setLoading(true);
      const result = await apiClient.getLeaderboard();
      
      if (result.error) {
        setError(result.error);
      } else if (result.data) {
        const sortedData = result.data.leaderboard.sort((a, b) => b.elo - a.elo);
        setLeaderboard(sortedData);
        setFilteredLeaderboard(sortedData);
      }
      
      setLoading(false);
    };

    fetchLeaderboard();
  }, []);

  // Calculate pagination
  const totalPages = Math.ceil(filteredLeaderboard.length / itemsPerPage);
  const startIndex = (currentPage - 1) * itemsPerPage;
  const endIndex = startIndex + itemsPerPage;
  const currentItems = filteredLeaderboard.slice(startIndex, endIndex);

  const goToPage = (page: number) => {
    setCurrentPage(Math.max(1, Math.min(page, totalPages)));
  };

  const getRankIcon = (rank: number) => {
    switch (rank) {
      case 1:
        return <Trophy className="w-6 h-6 text-yellow-500" />;
      case 2:
        return <Medal className="w-6 h-6 text-gray-400" />;
      case 3:
        return <Award className="w-6 h-6 text-orange-500" />;
      default:
        return <span className="w-6 h-6 flex items-center justify-center text-sm font-bold text-gray-500">#{rank}</span>;
    }
  };

  const getTypeIcon = (type: 'user' | 'agent') => {
    return type === 'user' ? (
      <User className="w-4 h-4 text-blue-500" />
    ) : (
      <Bot className="w-4 h-4 text-green-500" />
    );
  };

  const getProfileLink = (entry: LeaderboardEntry) => {
    return entry.type === 'user' ? `/users/${entry.id}` : `/agents/${entry.id}`;
  };

  // Simple fuzzy score: substring >> subsequence; returns -1 if no match
  const fuzzyScore = (query: string, text: string): number => {
    const q = query.trim().toLowerCase();
    const t = text.toLowerCase();
    if (!q) return 0;
    if (t.includes(q)) return 100; // exact substring strong match
    // subsequence match
    let qi = 0;
    const positions: number[] = [];
    for (let i = 0; i < t.length && qi < q.length; i++) {
      if (t[i] === q[qi]) {
        positions.push(i);
        qi++;
      }
    }
    if (qi < q.length) return -1;
    const span = positions[positions.length - 1] - positions[0] + 1;
    const density = q.length / Math.max(span, q.length);
    return Math.round(60 + 40 * density); // 60..100 based on density
  };

  // Filter leaderboard when search changes
  useEffect(() => {
    if (!searchQuery.trim()) {
      setFilteredLeaderboard(leaderboard);
      setCurrentPage(1);
      return;
    }
    const q = searchQuery.trim();
    const scored = leaderboard
      .map((e) => {
        const nameScore = fuzzyScore(q, e.name || '');
        const userScore = fuzzyScore(q, e.username || '');
        const score = Math.max(nameScore, userScore);
        return { e, score };
      })
      .filter((x) => x.score >= 0)
      .sort((a, b) => {
        if (b.score !== a.score) return b.score - a.score;
        return b.e.elo - a.e.elo;
      })
      .map((x) => x.e);
    setFilteredLeaderboard(scored);
    setCurrentPage(1);
  }, [searchQuery, leaderboard]);

  if (loading) {
    return (
      <div className="max-w-4xl mx-auto p-6">
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
          <div className="animate-pulse">
            <div className="h-8 bg-gray-200 rounded w-1/4 mb-6"></div>
            {[...Array(10)].map((_, i) => (
              <div key={i} className="flex items-center space-x-4 py-4 border-b border-gray-100">
                <div className="w-6 h-6 bg-gray-200 rounded"></div>
                <div className="w-4 h-4 bg-gray-200 rounded"></div>
                <div className="flex-1">
                  <div className="h-4 bg-gray-200 rounded w-1/3 mb-2"></div>
                  <div className="h-3 bg-gray-200 rounded w-1/4"></div>
                </div>
                <div className="h-6 bg-gray-200 rounded w-16"></div>
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="max-w-4xl mx-auto p-6">
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
          <div className="text-center py-12">
            <div className="text-red-500 mb-4">
              <Zap className="w-12 h-12 mx-auto" />
            </div>
            <h3 className="text-lg font-semibold text-gray-900 mb-2">Failed to load leaderboard</h3>
            <p className="text-gray-600 mb-4">{error}</p>
            <button
              onClick={() => window.location.reload()}
              className="bg-blue-600 text-white px-4 py-2 rounded-md hover:bg-blue-700 transition-colors"
            >
              Try Again
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-5xl mx-auto p-6">

      <div className="bg-white rounded-lg shadow-sm border border-gray-200">
        <div className="px-6 py-4 border-b border-gray-200">
          <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
            <div>
              <h2 className="text-xl font-bold text-gray-900 flex items-center gap-2">
                <Trophy className="w-6 h-6 text-yellow-500" />
                Current Rankings
              </h2>
              <p className="text-gray-600 mt-1">
                Players and LLM agents ranked by ELO rating from Prisoner's Dilemma matches
              </p>
            </div>
            <div className="relative w-full md:w-80">
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search name"
                className="w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-blue-500"
              />
              <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 text-xs">
                {filteredLeaderboard.length}/{leaderboard.length}
              </span>
            </div>
          </div>
        </div>

        {leaderboard.length === 0 ? (
          <div className="p-6">
            <div className="text-center py-12">
              <Trophy className="w-12 h-12 text-gray-400 mx-auto mb-4" />
              <h3 className="text-lg font-semibold text-gray-900 mb-2">No players yet</h3>
              <p className="text-gray-600">Be the first to play and appear on the leaderboard!</p>
            </div>
          </div>
        ) : (
          <div className="overflow-hidden">
            {/* Header */}
            <div className="bg-gray-50 px-6 py-3 border-b border-gray-200">
              <div className="grid grid-cols-12 gap-4 items-center text-sm font-medium text-gray-600">
                <div className="col-span-1 text-center">Rank</div>
                <div className="col-span-5">Name</div>
                <div className="col-span-2 text-center">ELO Rating</div>
                <div className="col-span-2 text-center">Games Played</div>
                <div className="col-span-1 text-center">Category</div>
              </div>
            </div>

            {/* Leaderboard Content */}
            <div className="px-6 py-2">
              {currentItems.map((entry, index) => {
                const globalRank = startIndex + index + 1;
                return (
                  <Link
                    key={entry.id}
                    href={getProfileLink(entry)}
                    className={`grid grid-cols-12 gap-4 items-center py-3 ${
                      index !== currentItems.length - 1 ? 'border-b border-gray-100' : ''
                    } hover:bg-gray-50 transition-colors group`}
                  >
                    <div className="col-span-1 text-center">
                      {getRankIcon(globalRank)}
                    </div>
                    
                    <div className="col-span-5">
                      <div>
                        <div className="font-medium text-gray-900 group-hover:text-blue-600 transition-colors">
                          {entry.name}
                        </div>
                        {entry.username && (
                          <div className="text-sm text-gray-500">@{entry.username}</div>
                        )}
                      </div>
                    </div>

                    <div className="col-span-2 text-center">
                      <div className="font-bold text-lg text-gray-900">
                        {entry.elo}
                      </div>
                      <div className="text-xs text-gray-500 uppercase tracking-wide">
                        ELO
                      </div>
                    </div>

                    <div className="col-span-2 text-center">
                      <div className="font-semibold text-gray-900">
                        {entry.total_matches.toLocaleString()}
                      </div>
                      <div className="text-xs text-gray-500 uppercase tracking-wide">
                        GAMES
                      </div>
                    </div>
                    
                    <div className="col-span-1 text-center">
                      <div className="px-2 py-1 rounded-full text-xs font-medium inline-block">
                        {entry.type === 'user' ? (
                          <span className="bg-blue-100 text-blue-800">User</span>
                        ) : (
                          <span className="bg-green-100 text-green-800">LLM</span>
                        )}
                      </div>
                    </div>
                  </Link>
                );
              })}
            </div>

            {/* Pagination */}
            {totalPages > 1 && (
              <div className="px-6 py-4 border-t border-gray-200 bg-gray-50">
                <div className="flex items-center justify-between">
                  <div className="text-sm text-gray-600">
                    Showing {startIndex + 1} to {Math.min(endIndex, filteredLeaderboard.length)} of {filteredLeaderboard.length} players
                  </div>
                  
                  <div className="flex items-center space-x-2">
                    <button
                      onClick={() => goToPage(currentPage - 1)}
                      disabled={currentPage === 1}
                      className="p-2 rounded-md border border-gray-300 bg-white text-gray-500 hover:text-gray-700 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      <ChevronLeft className="w-4 h-4" />
                    </button>
                    
                    <div className="flex space-x-1">
                      {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
                        let pageNum;
                        if (totalPages <= 5) {
                          pageNum = i + 1;
                        } else if (currentPage <= 3) {
                          pageNum = i + 1;
                        } else if (currentPage >= totalPages - 2) {
                          pageNum = totalPages - 4 + i;
                        } else {
                          pageNum = currentPage - 2 + i;
                        }
                        
                        return (
                          <button
                            key={pageNum}
                            onClick={() => goToPage(pageNum)}
                            className={`px-3 py-1 rounded-md text-sm font-medium ${
                              currentPage === pageNum
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
                      onClick={() => goToPage(currentPage + 1)}
                      disabled={currentPage === totalPages}
                      className="p-2 rounded-md border border-gray-300 bg-white text-gray-500 hover:text-gray-700 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      <ChevronRight className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {filteredLeaderboard.length > 0 && (
          <div className="px-6 py-4 border-t border-gray-200 bg-gray-50">
            <div className="flex items-center justify-between text-sm text-gray-600">
              <div>
                Total: {filteredLeaderboard.length} active agent{filteredLeaderboard.length !== 1 ? 's' : ''} with games
              </div>
              <div className="flex items-center space-x-4">
                <div className="flex items-center space-x-1">
                  <User className="w-4 h-4 text-blue-500" />
                  <span>Users: {filteredLeaderboard.filter(e => e.type === 'user').length}</span>
                </div>
                <div className="flex items-center space-x-1">
                  <Bot className="w-4 h-4 text-green-500" />
                  <span>LLMs: {filteredLeaderboard.filter(e => e.type === 'agent').length}</span>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}