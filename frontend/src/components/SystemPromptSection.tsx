"use client";

import { useCallback, useState } from "react";
import { apiClient } from "@/lib/api";

export default function SystemPromptSection() {
  const [expanded, setExpanded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [prompt, setPrompt] = useState<string | null>(null);

  const toggle = useCallback(async () => {
    const willExpand = !expanded;
    setExpanded(willExpand);
    if (willExpand && prompt == null && !loading) {
      setLoading(true);
      setError(null);
      const { data, error } = await apiClient.getSystemPrompt();
      if (error) setError(error);
      else setPrompt(data?.system_prompt ?? "");
      setLoading(false);
    }
  }, [expanded, prompt, loading]);

  return (
    <div className="mx-auto max-w-3xl text-left">
      <button
        type="button"
        onClick={toggle}
        className="w-full flex items-center justify-between rounded-md border border-gray-200 bg-white px-4 py-3 text-left shadow-sm hover:bg-gray-50"
      >
        <span className="font-medium">View Prompt</span>
        <svg
          className={`h-5 w-5 transition-transform ${expanded ? "rotate-180" : "rotate-0"}`}
          xmlns="http://www.w3.org/2000/svg"
          fill="none"
          viewBox="0 0 24 24"
          strokeWidth={1.5}
          stroke="currentColor"
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
        </svg>
      </button>

      {expanded && (
        <div className="mt-2 rounded-md border border-gray-200 bg-white p-4 shadow-sm">
          {loading && <div className="text-sm text-gray-500">Loading…</div>}
          {error && <div className="text-sm text-red-600">{error}</div>}
          {!loading && !error && (
            <pre className="whitespace-pre-wrap break-words text-sm text-gray-800 max-h-96 overflow-auto">{prompt}</pre>
          )}
        </div>
      )}
    </div>
  );
}


