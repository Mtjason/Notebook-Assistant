// A job's steps as they arrive over SSE (design.html, ProgressSteps): done steps ticked, the
// last one running while the job runs.
export function Steps({ steps, running }: { steps: string[]; running: boolean }) {
  return (
    <ol className="steps" aria-label="Progress">
      {steps.map((step, i) => (
        <li key={i} className={running && i === steps.length - 1 ? "run" : "ok"}>
          {step}
        </li>
      ))}
    </ol>
  );
}
