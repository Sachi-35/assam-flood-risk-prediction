/** Shows the backend's own disclaimer text verbatim. */
export function Disclaimer({ text }: { text: string | null | undefined }) {
  if (!text) return null;
  return (
    <aside className="disclaimer" role="note">
      <strong>Read this first.</strong> {text}
    </aside>
  );
}
