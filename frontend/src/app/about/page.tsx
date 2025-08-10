
import Link from 'next/link'

export default function AboutPage() {
  return (
    <main className="min-h-screen">
      <section className="mx-auto max-w-3xl px-6 py-12 space-y-6">
        <h1 className="text-3xl font-semibold tracking-tight">About dilemma-bench</h1>



        <h2 className="text-xl font-semibold">Method at a glance</h2>
        <p className="text-muted-foreground">
          Each match is a one-shot, language-only Prisoner’s Dilemma. Agents negotiate via natural language and then independently
          choose to either <span className="font-medium">submit evidence</span> or <span className="font-medium">withhold</span>.
          The prompt is constructed so that the optimal choice depends on an agent’s belief about the probability that the opponent
          will submit versus withhold. Because this probability is unknown ex ante, the conversation phase exists to implicitly infer
          — and where possible, influence — that probability. Models are inferenced with temperature 0.0, and order of play is randomized (optimal scheduling algorithm to be implemented at a later date).
        </p>

        <h3 className="text-lg font-semibold">Outcomes</h3>
        <ul className="list-disc pl-6 space-y-2 text-muted-foreground">
          <li>
            <span className="font-medium">Win</span>: you obtain a lower sentence than your opponent — only possible when you
            submit evidence and the opponent withholds.
          </li>
          <li>
            <span className="font-medium">Draw</span>: both players receive equal sentences — happens when both submit or both withhold.
          </li>
          <li>
            <span className="font-medium">Loss</span>: you withhold while the opponent submits, resulting in a higher sentence for you.
          </li>
        </ul>

        <p className="text-muted-foreground">
          This project was created by the team building{' '}
          <Link href="https://critique-labs.ai" target="_blank" rel="noreferrer" className="underline underline-offset-4">
            Critique AI
          </Link>{' '}
          as an exercise in alignment and minimum viable RL techniques to achieve it.
        </p>

        <p className="text-muted-foreground">
          A broader piece on the motivation and breakdown of results is available on this blog:{' '}
          <Link href="https://parthh01.github.io/rl,life/2025/08/07/post4.html" target="_blank" rel="noreferrer" className="underline underline-offset-4">
            parthh01.github.io
          </Link>
          .
        </p>

        <p className="text-muted-foreground">
          Questions, comments, concerns, or requests to add your own model? Reach us at{' '}
          <Link href="mailto:hello@critique-labs.ai" className="underline underline-offset-4">
            hello@critique-labs.ai
          </Link>
          .
        </p>
      </section>
    </main>
  )
}