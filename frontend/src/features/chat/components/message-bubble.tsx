/** The reader's own question: a quiet right-aligned bubble (assistant prose has no bubble). */
export function UserBubble({ text }: { text: string }) {
  return (
    <div className="mb-5 mt-1.5 flex justify-end">
      <div className="max-w-[80%] whitespace-pre-wrap rounded-[20px] rounded-br-md border border-border/60 bg-card-2 px-[15px] py-2.5 text-body">
        {text}
      </div>
    </div>
  );
}
