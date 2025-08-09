'use client';

import Link from 'next/link';
import { ExternalLink, Github, Brain } from 'lucide-react';

export default function Footer() {
  return (
    <footer className="bg-gray-900 text-white">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="border-t border-gray-800">
          <div className="flex flex-col md:flex-row justify-between items-center">
            <div className="text-sm text-gray-400 mb-4 md:mb-0">
              <p>
                © 2024 Critique AI. Built for alignment research. 
                <span className="ml-2">
                  Exploring verifiable measures of strategic AI behavior.
                </span>
              </p>
            </div>
            <div className="flex items-center space-x-4 text-sm text-gray-400">
              <Link href="/" className="hover:text-white transition-colors">
                Leaderboard
              </Link>
              <a
                href="https://critique-labs.ai"
                target="_blank"
                rel="noopener noreferrer"
                className="hover:text-white transition-colors"
              >
                Research
              </a>
            </div>
          </div>
        </div>
      </div>
    </footer>
  );
}