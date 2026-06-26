import { renderMarkdown } from '../../lib/markdown';

interface Props {
  markdown: string | null;
}

/** Renders the Synthesizer's markdown output. */
export function MarkdownView({ markdown }: Props) {
  if (!markdown) return null;
  return (
    <article
      className="prose-discover text-sm text-ink leading-relaxed"
      // The renderer is local + escapes every interpolation; no user-supplied HTML reaches it.
      dangerouslySetInnerHTML={{ __html: renderMarkdown(markdown) }}
    />
  );
}
