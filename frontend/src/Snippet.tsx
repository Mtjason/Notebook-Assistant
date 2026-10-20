// A search snippet: the service marks matches as **word**; show them bold, everything as text
// (never as HTML).
export function Snippet({ text }: { text: string }) {
  const parts = text.split("**");
  return (
    <span className="snippet">
      {parts.map((part, i) => (i % 2 === 1 ? <b key={i}>{part}</b> : <span key={i}>{part}</span>))}
    </span>
  );
}
