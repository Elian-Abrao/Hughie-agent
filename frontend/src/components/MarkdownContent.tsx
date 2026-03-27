import ReactMarkdown from "react-markdown";
import rehypeHighlight from "rehype-highlight";

interface Props {
  content: string;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const rehypePlugins: any[] = [rehypeHighlight];

export function MarkdownContent({ content }: Props) {
  return (
    <ReactMarkdown className="prose-chat" rehypePlugins={rehypePlugins}>
      {content}
    </ReactMarkdown>
  );
}
