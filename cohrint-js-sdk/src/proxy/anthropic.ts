import { buildEvent } from "./universal.js";
import { VantageClient } from "../client.js";

type AnyFn = (...args: unknown[]) => unknown;

function extractSystemPrompt(system: unknown): string {
  if (!system) return "";
  if (typeof system === "string") return system;
  if (Array.isArray(system)) return system.map((b: { text?: string }) => b.text ?? "").join("\n");
  return "";
}

function extractLastUserMessage(messages: Array<{ role: string; content: unknown }>): string {
  const last = [...messages].reverse().find((m) => m.role === "user");
  if (!last) return "";
  if (typeof last.content === "string") return last.content;
  if (Array.isArray(last.content)) {
    return (last.content as Array<{ type: string; text?: string }>)
      .filter((b) => b.type === "text")
      .map((b) => b.text ?? "")
      .join("");
  }
  return "";
}

function wrapMessagesCreate(originalCreate: AnyFn, client: VantageClient) {
  return async function (this: unknown, params: Record<string, unknown>) {
    const { model = "", messages = [], system, stream, ...rest } = params as {
      model: string;
      messages: Array<{ role: string; content: unknown }>;
      system?: unknown;
      stream?: boolean;
      max_tokens?: number;
      [k: string]: unknown;
    };

    const systemPrompt = extractSystemPrompt(system);
    const lastUserMessage = extractLastUserMessage(messages);
    const t0 = performance.now();
    let ttftMs = 0;
    let statusCode = 200;

    try {
      if (stream) {
        const rawStream = await (originalCreate as AnyFn).call(this, {
          model, messages, system, stream: true, ...rest,
        }) as AsyncIterable<{
          type: string;
          message?: { usage?: { input_tokens: number; cache_read_input_tokens?: number } };
          index?: number;
          delta?: { type: string; text?: string };
          usage?: { output_tokens: number };
        }>;

        let responseText = "";
        let promptTokens = 0;
        let completionTokens = 0;
        let cachedTokens = 0;
        let firstContent = true;

        async function* wrapped() {
          for await (const chunk of rawStream) {
            if (chunk.type === "message_start" && chunk.message?.usage) {
              promptTokens = chunk.message.usage.input_tokens ?? 0;
              cachedTokens = chunk.message.usage.cache_read_input_tokens ?? 0;
            }
            if (chunk.type === "content_block_delta" && chunk.delta?.type === "text_delta") {
              if (firstContent) { ttftMs = performance.now() - t0; firstContent = false; }
              responseText += chunk.delta.text ?? "";
            }
            if (chunk.type === "message_delta" && chunk.usage) {
              completionTokens = chunk.usage.output_tokens ?? 0;
            }
            yield chunk;
          }

          const latencyMs = performance.now() - t0;
          const event = buildEvent({
            provider: "anthropic", model, endpoint: "/messages",
            promptTokens, completionTokens, cachedTokens, latencyMs, ttftMs, statusCode,
            promptText: lastUserMessage, responseText, systemPrompt,
            orgId: client.orgId, environment: client.environment,
          });
          client.capture(event);
        }

        return wrapped();
      }

      // Non-streaming
      const response = await (originalCreate as AnyFn).call(this, {
        model, messages, system, ...rest,
      }) as {
        content: Array<{ type: string; text?: string }>;
        usage?: { input_tokens: number; output_tokens: number; cache_read_input_tokens?: number };
      };

      const latencyMs = performance.now() - t0;
      const usage = response.usage;
      const responseText = response.content
        .filter((b) => b.type === "text")
        .map((b) => b.text ?? "")
        .join("");

      const event = buildEvent({
        provider: "anthropic", model, endpoint: "/messages",
        promptTokens: usage?.input_tokens ?? 0,
        completionTokens: usage?.output_tokens ?? 0,
        cachedTokens: usage?.cache_read_input_tokens ?? 0,
        latencyMs, statusCode,
        promptText: lastUserMessage, responseText, systemPrompt,
        orgId: client.orgId, environment: client.environment,
      });
      client.capture(event);
      return response;

    } catch (err: unknown) {
      statusCode = (err as { status?: number }).status ?? 500;
      const latencyMs = performance.now() - t0;
      const event = buildEvent({
        provider: "anthropic", model, endpoint: "/messages",
        promptTokens: 0, completionTokens: 0, latencyMs, statusCode,
        error: (err as Error).message ?? String(err),
        promptText: lastUserMessage, systemPrompt,
        orgId: client.orgId, environment: client.environment,
      });
      client.capture(event);
      throw err;
    }
  };
}

export function createAnthropicProxy<T extends object>(anthropicClient: T, vantageClient: VantageClient): T {
  const wrappedCreate = wrapMessagesCreate(
    ((anthropicClient as Record<string, unknown>)["messages"] as Record<string, unknown>)["create"] as AnyFn,
    vantageClient
  );

  return new Proxy(anthropicClient, {
    get(target, prop) {
      if (prop === "messages") {
        return new Proxy((target as Record<string, unknown>)["messages"] as object, {
          get(msgTarget, msgProp) {
            if (msgProp === "create") return wrappedCreate;
            return (msgTarget as Record<string, unknown>)[msgProp as string];
          },
        });
      }
      return (target as Record<string, unknown>)[prop as string];
    },
  });
}
