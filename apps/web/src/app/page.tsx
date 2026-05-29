import { ChatShell } from "@/components/ChatShell";
import { DisclaimerFooter } from "@/components/DisclaimerFooter";

export default function Home() {
  return (
    <div className="flex min-h-screen flex-col bg-white dark:bg-zinc-950">
      <main className="mx-auto flex min-h-0 w-full max-w-3xl flex-1 flex-col border-x border-zinc-200 dark:border-zinc-800">
        <ChatShell />
      </main>
      <DisclaimerFooter />
    </div>
  );
}
