"use client";

import { useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import {
  ArrowUp,
  Boxes,
  Check,
  CircleHelp,
  PackageSearch,
  ShieldCheck,
  Sparkles,
  Square,
  Warehouse,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { streamChat } from "@/lib/chat-stream";

type Message = {
  id: number;
  role: "user" | "assistant";
  content: string;
  error?: boolean;
};

const EXAMPLES = [
  {
    icon: Warehouse,
    title: "查询仓库库存",
    prompt: "DEMO-WH-01 仓库的 DEMO-SKU-001 有多少可用库存？",
  },
  {
    icon: PackageSearch,
    title: "查看库位明细",
    prompt: "请查询 DEMO-WH-01 中 DEMO-SKU-001 的库位和库存分布。",
  },
  {
    icon: Boxes,
    title: "了解在途数量",
    prompt: "DEMO-WH-01 仓库的 DEMO-SKU-002 有多少在途库存？",
  },
];

export function ChatWorkspace() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const nextId = useRef(0);
  const bottomRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    requestAnimationFrame(() => bottomRef.current?.scrollIntoView({ behavior: "smooth" }));
  };

  const submit = async (rawMessage: string) => {
    const question = rawMessage.trim();
    if (!question || isStreaming) return;

    setError(null);
    setDraft("");
    const userId = nextId.current++;
    const assistantId = nextId.current++;
    setMessages((current) => [
      ...current,
      { id: userId, role: "user", content: question },
      { id: assistantId, role: "assistant", content: "" },
    ]);
    setIsStreaming(true);
    scrollToBottom();

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      await streamChat(question, controller.signal, {
        onDelta: (text) => {
          setMessages((current) =>
            current.map((message) =>
              message.id === assistantId
                ? { ...message, content: message.content + text }
                : message,
            ),
          );
          scrollToBottom();
        },
      });
    } catch (streamError) {
      if (!controller.signal.aborted) {
        const message =
          streamError instanceof Error ? streamError.message : "聊天请求失败，请稍后重试。";
        setError(message);
        setMessages((current) => {
          const hasText = current.some(
            (item) => item.id === assistantId && item.content.length > 0,
          );
          if (hasText) return current;
          return current.filter((item) => item.id !== assistantId);
        });
      }
    } finally {
      setMessages((current) =>
        current.filter(
          (message) => message.id !== assistantId || message.content.length > 0,
        ),
      );
      if (abortRef.current === controller) abortRef.current = null;
      setIsStreaming(false);
    }
  };

  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void submit(draft);
  };

  const onComposerKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      void submit(draft);
    }
  };

  const stop = () => abortRef.current?.abort();
  const isEmpty = messages.length === 0;

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-6xl flex-col px-4 py-5 sm:px-7 sm:py-8">
      <header className="mb-7 flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="flex size-11 items-center justify-center rounded-2xl bg-primary text-white shadow-lg shadow-blue-900/15">
            <Warehouse size={22} strokeWidth={2.2} />
          </div>
          <div>
            <p className="text-sm font-semibold tracking-wide text-foreground">云仓运营助手</p>
            <p className="mt-0.5 text-xs text-muted-foreground">YUNCANG COPILOT · 本地模拟环境</p>
          </div>
        </div>
        <div className="hidden items-center gap-2 rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-xs font-medium text-emerald-700 sm:flex">
          <span className="size-1.5 rounded-full bg-emerald-500" />
          只读数据已连接
        </div>
      </header>

      <section className="mb-5 grid gap-3 rounded-2xl border border-blue-100 bg-white/80 p-4 text-sm leading-6 text-slate-600 shadow-sm sm:grid-cols-[auto_1fr] sm:items-start sm:gap-4 sm:p-5">
        <div className="flex size-9 items-center justify-center rounded-xl bg-blue-50 text-primary">
          <ShieldCheck size={19} />
        </div>
        <p>
          <strong className="font-semibold text-slate-800">安全只读模式。</strong>
          助手仅根据本项目虚构的仓库数据回答库存问题，不会修改库存或订单；回答内容请以查询结果为准。
        </p>
      </section>

      <section className="flex flex-1 flex-col">
        {isEmpty ? (
          <div className="flex flex-1 flex-col items-center justify-center pb-8 pt-7 text-center sm:pt-12">
            <div className="mb-5 flex size-16 items-center justify-center rounded-3xl border border-blue-100 bg-white text-primary shadow-sm">
              <Sparkles size={27} />
            </div>
            <p className="mb-2 text-xs font-semibold uppercase tracking-[0.2em] text-primary">
              Inventory assistant
            </p>
            <h1 className="max-w-xl text-3xl font-semibold tracking-tight text-slate-900 sm:text-4xl">
              今天想了解哪项库存？
            </h1>
            <p className="mt-3 max-w-lg text-sm leading-6 text-muted-foreground sm:text-base">
              说出仓库和商品编码，我会查询可用数量、库位明细及在途库存。
            </p>

            <div className="mt-9 grid w-full max-w-4xl gap-3 text-left md:grid-cols-3">
              {EXAMPLES.map(({ icon: Icon, title, prompt }) => (
                <button
                  key={title}
                  type="button"
                  onClick={() => void submit(prompt)}
                  disabled={isStreaming}
                  className="group rounded-2xl text-left outline-none focus-visible:ring-2 focus-visible:ring-primary"
                >
                  <Card className="h-full border-slate-200/90 p-4 transition-all group-hover:-translate-y-0.5 group-hover:border-blue-200 group-hover:shadow-md">
                    <div className="mb-4 flex items-center justify-between">
                      <span className="flex size-9 items-center justify-center rounded-xl bg-slate-100 text-slate-600 transition-colors group-hover:bg-blue-50 group-hover:text-primary">
                        <Icon size={18} />
                      </span>
                      <ArrowUp size={15} className="text-slate-300 transition-colors group-hover:text-primary" />
                    </div>
                    <p className="text-sm font-semibold text-slate-800">{title}</p>
                    <p className="mt-1.5 text-xs leading-5 text-muted-foreground">{prompt}</p>
                  </Card>
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-5 py-3 sm:py-6">
            {messages.map((message) => (
              <div
                key={message.id}
                className={`flex gap-3 ${message.role === "user" ? "justify-end" : "justify-start"}`}
              >
                {message.role === "assistant" && (
                  <div className="mt-1 flex size-8 shrink-0 items-center justify-center rounded-xl bg-primary text-white">
                    <Sparkles size={16} />
                  </div>
                )}
                <div
                  className={`max-w-[88%] whitespace-pre-wrap break-words rounded-2xl px-4 py-3 text-sm leading-7 sm:max-w-[78%] ${
                    message.role === "user"
                      ? "rounded-br-md bg-primary text-white shadow-sm"
                      : "rounded-bl-md border border-slate-200 bg-white text-slate-700 shadow-sm"
                  }`}
                >
                  {message.content || (
                    <span className="inline-flex items-center gap-2 text-muted-foreground">
                      <span className="flex gap-1">
                        <i className="size-1.5 animate-bounce rounded-full bg-slate-400 [animation-delay:-0.2s]" />
                        <i className="size-1.5 animate-bounce rounded-full bg-slate-400 [animation-delay:-0.1s]" />
                        <i className="size-1.5 animate-bounce rounded-full bg-slate-400" />
                      </span>
                      正在查询
                    </span>
                  )}
                  {message.role === "assistant" && message.content && isStreaming && (
                    <span className="ml-1 inline-block h-4 w-1 animate-pulse rounded-full bg-primary align-middle" />
                  )}
                </div>
                {message.role === "user" && (
                  <div className="mt-1 flex size-8 shrink-0 items-center justify-center rounded-xl bg-slate-200 text-xs font-semibold text-slate-600">
                    我
                  </div>
                )}
              </div>
            ))}
            {error && (
              <div className="flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700" role="alert">
                <CircleHelp size={17} className="mt-0.5 shrink-0" />
                <span>{error}</span>
              </div>
            )}
            {!isStreaming && !error && messages.some((message) => message.role === "assistant" && message.content) && (
              <div className="flex items-center gap-1.5 pl-11 text-xs text-muted-foreground">
                <Check size={14} className="text-emerald-600" />
                已基于模拟库存数据完成查询
              </div>
            )}
            <div ref={bottomRef} />
          </div>
        )}

        {isEmpty && error && (
          <div className="mx-auto mb-3 w-full max-w-3xl rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700" role="alert">
            {error}
          </div>
        )}

        <div className="sticky bottom-0 mx-auto mt-5 w-full max-w-3xl pb-2 pt-2 sm:pb-5">
          <Card className="border-slate-200 bg-white p-2 shadow-lg shadow-slate-900/[0.04]">
            <form onSubmit={onSubmit}>
              <label htmlFor="chat-input" className="sr-only">输入库存问题</label>
              <Textarea
                id="chat-input"
                rows={2}
                maxLength={2000}
                placeholder="例如：DEMO-WH-01 中 DEMO-SKU-001 有多少可用库存？"
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={onComposerKeyDown}
                disabled={isStreaming}
                className="min-h-14 border-0 bg-transparent px-3 py-3 shadow-none focus-visible:border-transparent focus-visible:ring-0"
              />
              <div className="flex items-center justify-between px-2 pb-1">
                <p className="text-[11px] text-muted-foreground">Enter 发送 · Shift + Enter 换行</p>
                {isStreaming ? (
                  <Button type="button" size="icon" variant="outline" onClick={stop} aria-label="停止生成">
                    <Square size={15} fill="currentColor" />
                  </Button>
                ) : (
                  <Button type="submit" size="icon" disabled={!draft.trim()} aria-label="发送问题">
                    <ArrowUp size={18} />
                  </Button>
                )}
              </div>
            </form>
          </Card>
          <p className="mt-3 text-center text-[11px] leading-5 text-slate-400">
            内容仅供本地模拟环境演示；库存口径以项目测试和数据定义为准。
          </p>
        </div>
      </section>
    </main>
  );
}
