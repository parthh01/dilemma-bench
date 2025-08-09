import LeaderboardPage from '@/components/LeaderboardPage';
import { ComicText } from "@/components/magicui/comic-text";
import PayoffMatrix from '@/components/PayoffMatrix';
import SystemPromptSection from '@/components/SystemPromptSection';

export default function Home() {
  return (
    <div>
        <div className="max-w-5xl mx-auto px-6 py-12 text-center">
          <div className="relative mx-auto mb-8 h-40 md:h-56 lg:h-64 w-full overflow-hidden rounded-lg">
          <div className="space-y-8 text-center mt-8">
      <ComicText fontSize={5}>Dilemma Bench</ComicText>
    </div>
          </div>
          {/* Visual Payoff Matrix */}
          <PayoffMatrix />
          <p className="text-lg text-gray-600 max-w-2xl mx-auto mt-4">
            <a href="https://en.wikipedia.org/wiki/Prisoner%27s_dilemma" className="text-blue-600 hover:text-blue-700 underline">The Prisoner's Dilemma</a> formulated as a turn-based conversational game. This benchmark serves a vector into the purported alignment of large language models. 
          </p>
          <div className="mt-6">
            <SystemPromptSection />
          </div>
          <div className="mt-8 flex items-center justify-center gap-3">
            <a href="#leaderboard" className="inline-flex items-center justify-center rounded-md bg-blue-600 px-5 py-3 text-sm font-semibold text-white hover:bg-blue-700 transition-colors">
              Leaderboard
            </a>
          </div>
        </div>

      {/* Leaderboard Preview */}
      <section id="leaderboard" className="scroll-mt-24">
        <LeaderboardPage />
      </section>
    </div>
  );
}