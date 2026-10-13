import type { NextRequest } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const MAX_MESSAGE_LENGTH = 2000;
const SAFE_ERROR = "聊天服务暂时不可用，请稍后重试。";

/**
 * Proxy chat requests to FastAPI without buffering the event stream.
 * The upstream address is server configuration, never supplied by the browser.
 */
export async function POST(request: NextRequest): Promise<Response> {
  let body: unknown;

  try {
    body = await request.json();
  } catch {
    return Response.json({ detail: "请求必须是有效的 JSON。" }, { status: 400 });
  }

  if (
    typeof body !== "object" ||
    body === null ||
    !("message" in body) ||
    typeof body.message !== "string" ||
    body.message.trim().length === 0 ||
    body.message.length > MAX_MESSAGE_LENGTH
  ) {
    return Response.json(
      { detail: "问题长度必须为 1 到 2000 个字符。" },
      { status: 422 },
    );
  }

  const backendUrl = process.env.BACKEND_API_URL ?? "http://127.0.0.1:8000";

  try {
    const upstream = await fetch(`${backendUrl.replace(/\/$/, "")}/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify({ message: body.message }),
      cache: "no-store",
      signal: request.signal,
    });

    const headers = new Headers();
    const contentType = upstream.headers.get("content-type");
    if (contentType) headers.set("Content-Type", contentType);
    headers.set("Cache-Control", "no-cache, no-transform");
    headers.set("X-Accel-Buffering", "no");

    return new Response(upstream.body, {
      status: upstream.status,
      headers,
    });
  } catch {
    return Response.json({ detail: SAFE_ERROR }, { status: 502 });
  }
}
