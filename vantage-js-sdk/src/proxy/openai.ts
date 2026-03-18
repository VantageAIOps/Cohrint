import { buildEvent } from "./universal.js";
import { VantageClient } from "../client.js";

type AnyFn = (...args: unknown[]) => unknown;

function extractMessages(messages: Array<{ role: string; content: string }>): {
  systemPrompt: string;
  lastUserMessage: string;
} {
  const systemPrompt = messages
    .filter((m) => m.role === "system")
    .map((m) => m.content)
    .join("\n");
  const lastUser = [...messages].reverse().find((m) => m.role === "user");
  return { systemPrompt, lastUserMessage: lastUser?.content ?? "" };
}

function wrapCreate(originalCreate: AnyFn, client: VantageClient) {
  return async function (this: unknown, params: Record<string, unknown>) {
    const { model = "", messages = [], stream, ...rest } = params as {
      model: string;
      messages: Array<{ role: string; content: string }>;
      stream?: boolean;
      [k: string]: unknown;
    };

    const { systemPrompt, lastUserMessage } = extractMessages(messages);
    const t0 = performance.now();
    let ttftMs = 0;
    let statusCode = 200;
    let errorMsg: string | undefined;

    try {
      if (stream) {
        // Streaming path
        const rawStream = await (originalCreate as AnyFn).call(this, { model, messages, stream: true, ...rest }) as AsyncIterable<{
          choices?: Array<{ delta?: { content?: string } }>;
          usage?: { prompt_tokens: number; completion_tokens: number };
        }>;

        let responseText = "";
        let promptTokens = 0;
        let completionTokens = 0;
        let firstChunk = true;

        async function* wrapped() {
          for await (const chunk of rawStream) {
            if (firstChunk) { ttftMs = performance.now() - t0; firstChunk = false; }
            const delta = chunk.choices?.[0]?.delta?.content ?? "";
            responseText += delta;
            if (chunk.usage) {
              promptTokens = chunk.usage.prompt_tokens ?? 0;
              completionTokens = chunk.usage.completion_tokens ?? 0;
            }
            yield chunk;
          }

          const latencyMs = performance.now() - t0;
          const event = buildEvent({
            provider: "openai", model, endpoint: "/chat/completions",
            promptTokens, completionTokens, latencyMs, ttftMs, statusCode,
            promptText: lastUserMessage, responseText, systemPrompt,
            orgId: client.orgId, environment: client.environment,
          });
          client.capture(event);
        }

        return wrapped();
      }

      // Non-streaming path
      const response = await (originalCreate as AnyFn).call(this, { model, messages, ...rest }) as {
        choices: Array<{ message: { content: string } }>;
        usage?: { prompt_tokens: number; completion_tokens: number; cached_tokens?: number };
      };

      const latencyMs = performance.now() - t0;
      const usage = response.usage;
      const responseText = response.choices?.[0]?.message?.content ?? "";

      const event = buildEvent({
        provider: "openai", model, endpoint: "/chat/completions",
        promptTokens: usage?.prompt_tokens ?? 0,
        completionTokens: usage?.completion_tokens ?? 0,
        cachedTokens: usage?.cached_tokens ?? 0,
        latencyMs, statusCode,
        promptText: lastUserMessage, responseText, systemPrompt,
        orgId: client.orgId, environment: client.environment,
      });
      client.capture(event);
      return response;

    } catch (err: unknown) {
      statusCode = (err as { status?: number }).status ?? 500;
      errorMsg = (err as Error).message ?? String(err);
      const latencyMs = performance.now() - t0;
      const event = buildEvent({
        provider: "openai", model, endpoint: "/chat/completions",
        promptTokens: 0, completionTokens: 0, latencyMs, statusCode, error: errorMsg,
        promptText: lastUserMessage, systemPrompt,
        orgId: client.orgId, environment: client.environment,
      });
      client.capture(event);
      throw err;
    }
  };
}

export function createOpenAIProxy<T extends object>(openaiClient: T, vantageClient: VantageClient): T {
  const original = (openaiClient as Record<string, unknown>);

  const wrappedCreate = wrapCreate(
    (original["chat"] as Record<string, unknown>)?.["completions"]?.["create"] as AnyFn,
    vantageClient
  );

  return new Proxy(openaiClient, {
    get(target, prop) {
      if (prop === "chat") {
        return new Proxy((target as Record<string, unknown>)["chat"] as object, {
          get(chatTarget, chatProp) {
            if (chatProp === "completions") {
              return new Proxy((chatTarget as Record<string, unknown>)["completions"] as object, {
                get(compTarget, compProp) {
                  if (compProp === "create") return wrappedCreate;
                  return (compTarget as Record<string, unknown>)[compProp as string];
                },
              });
            }
            return (chatTarget as Record<string, unknown>)[chatProp as string];
          },
        });
      }
      return (target as Record<string, unknown>)[prop as string];
    },
  });
}
