import { createHash } from "node:crypto";
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { answerRagRulingQuestion, finalizePreparedRagRulingQuestion } from "./reference-rag-pins/backend/ragRulingPipeline.mjs";
import { retrieveRagEvidence } from "./reference-rag-pins/backend/ragEvidenceRetriever.mjs";
import { buildRagRulingPromptBundle } from "./reference-rag-pins/backend/ragRulingPrompt.mjs";

const load = async path => JSON.parse(await readFile(path, "utf8"));
const hash = value => createHash("sha256").update(value).digest("hex");
const pointer = await load("reference-rag-corpora/current.json");
if (!/^[a-f0-9]{40}$/u.test(pointer.commit)) throw new Error("Invalid corpus commit");
const dataDir = resolve("reference-rag-corpora", pointer.commit);
if ((await load(resolve(dataDir, "rag-data-revision-manifest.json"))).revision !== pointer.revision) {
  throw new Error("Corpus revision mismatch");
}
const key = process.env.YGO_RULING_OPENAI_API_KEY;
if (!key) throw new Error("Missing ruling API key");
const model = "gpt-6.2-sol";
const env = {
  RAG_MODEL_PROVIDER: "deepseek", DEEPSEEK_MODEL: model,
  RAG_CARD_MODEL_PROVIDER: "deepseek", DEEPSEEK_CARD_MODEL: model,
  RAG_RULE_MODEL_PROVIDER: "relay", DEEPSEEK_RULE_MODEL: model,
  DEEPSEEK_BASE_URL: "https://transport.invalid/v1", DEEPSEEK_API_KEY: "injected-invoker",
  RELAY_BASE_URL: "https://transport.invalid/v1", RELAY_API_KEY: "injected-invoker",
  RAG_RULE_QUERY_EXTRACTOR_ENABLED: "true", RAG_LIVE_OFFICIAL_QA: "false",
  RAG_EVIDENCE_APPLICABILITY_ENABLED: "false",
};
const noNetwork = async () => { throw new Error("Only the configured model transport may use the network"); };

function estimateCost(usage) {
  const cached = usage.input_tokens_details?.cached_tokens ?? 0;
  const written = usage.input_tokens_details?.cache_write_tokens ?? 0;
  const ordinary = usage.input_tokens - cached - written;
  const long = usage.input_tokens > 272_000;
  return (ordinary * (long ? 4 : 2) + cached * (long ? 0.2 : 0.1)
    + written * (long ? 5 : 2.5) + usage.output_tokens * (long ? 15 : 10)) / 1e6;
}

async function adjudicate(question, signal) {
  const startedAt = performance.now();
  const timings = {};
  const trace = [];
  let cost = 0;
  const invoke = async (stage, prompt, stageSignal) => {
    const start = performance.now();
    const entry = { stage };
    trace.push(entry);
    try {
      const reply = await fetch("https://api.openai.com/v1/responses", {
        method: "POST",
        headers: { authorization: "Bearer " + key, "content-type": "application/json" },
        signal: stageSignal ? AbortSignal.any([signal, stageSignal]) : signal,
        body: JSON.stringify({ model, input: prompt, reasoning: { effort: "high" }, store: false }),
      });
      if (!reply.ok) throw new Error("OpenAI HTTP " + reply.status);
      const data = await reply.json();
      if (data.usage && data.model === model) {
        const { input_tokens, output_tokens, total_tokens } = data.usage;
        entry.usage = { input_tokens, output_tokens, total_tokens };
        cost += estimateCost(data.usage);
      }
      const text = data.output?.flatMap(item => item.content ?? [])
        .filter(item => item.type === "output_text").map(item => item.text).join("");
      if (data.status !== "completed" || data.model !== model || !text?.trim()) {
        throw new Error("Incomplete or unexpected model response");
      }
      entry.completed = true;
      return text;
    } finally {
      entry.elapsed_ms = Math.round(performance.now() - start);
    }
  };

  const prepared = await answerRagRulingQuestion({
    question, dataDir, env, fetchImpl: noNetwork, prepareForContinuation: true,
    cardModelInvoker: ({ prompt, signal }) => invoke("card_resolution", prompt, signal),
    ruleModelInvoker: ({ prompt, signal }) => invoke("rule_query_extraction", prompt, signal),
  });
  let result = prepared, loopStatus = "direct_answer";
  timings.preparation = prepared.continuation?.timingsMs ?? prepared.debug?.timingsMs;
  function recordRetrieval(pass, debug) {
    if (debug?.timingsMs) timings[pass] = {
      ...debug.timingsMs, crossCardPoolCacheHit: debug.crossCardPoolCacheHit,
    };
  }
  if (prepared.status === "evidence_prepared") {
    const first = prepared.continuation;
    recordRetrieval("initialRetrieval", first.evidence.debug);
    if (first.dataRevision !== pointer.revision) throw new Error("Unexpected prepared corpus revision");
    const finalize = async (continuation, stage) => {
      const answer = await finalizePreparedRagRulingQuestion({
        continuation, env, fetchImpl: noNetwork,
        modelInvoker: ({ prompt, signal }) => invoke(stage, prompt, signal),
      });
      if (!answer.shortAnswer?.trim() || trace.at(-1)?.stage !== stage || !trace.at(-1).completed) {
        throw new Error("Upstream finalization did not yield an answer");
      }
      return answer;
    };
    result = await finalize(first, "baseline");
    loopStatus = "no_gap";
    try {
      const auditPrompt = [
        "检查已提交的游戏王 OCG 裁定答复是否完整、有直接适用的证据。此步骤只决定是否再检索，不作答。",
        "逐一核对用户要求的结论和独立时点。草稿语气确定也不代表有证据。区分「用户缺少局面信息」和「证据缺少可检索的规则」，前者不触发补查。",
        "仅输出 JSON 对象 {gap,queries}。证据足够或缺少局面信息时 gap 为空字符串、queries 为空数组。",
        "发现实质性规则缺口时用中文概述 gap，给 1 至 3 条查询，每条包含 subclaim、checkpoint、officialQuestion（日语官方问法）、scenarioQuestion（完整问题，可用中文）。",
        "查询应单独核实决定性规则、适用例外或相反情形，不猜答案，不把搜索词当成新局面事实。以下为待检查数据。",
        JSON.stringify({ draft: result.shortAnswer }),
        first.promptBundle.prompt,
      ].join("\n");
      const raw = await invoke("coverage_audit", auditPrompt);
      const audit = JSON.parse(raw.trim().replace(/^```(?:json)?\s*|\s*```$/giu, ""));
      if (typeof audit?.gap !== "string" || !Array.isArray(audit.queries) || audit.queries.length > 3
          || Boolean(audit.gap.trim()) !== Boolean(audit.queries.length)) throw new Error("Invalid audit");
      const fields = ["subclaim", "checkpoint", "officialQuestion", "scenarioQuestion"];
      const queries = audit.queries.map(item => Object.fromEntries(fields.map(field => {
        if (typeof item[field] !== "string" || !item[field].trim()) throw new Error("Invalid audit query");
        return [field, item[field].trim().slice(0, 220)];
      })));
      if (queries.length) {
        const retrieved = await retrieveRagEvidence({
          userQuery: question, cardResolution: first.cardResolution,
          ruleSearchQueries: [...queries, ...(first.evidence.ruleSearchQueries ?? [])],
          dataDir, env, fetchImpl: noNetwork, signal,
        });
        recordRetrieval("supplementRetrieval", retrieved.debug);
        const evidence = { ...first.evidence, ruleSearchQueries: retrieved.ruleSearchQueries };
        for (const bucket of ["officialQaRelated", "provisionalOfficialResponses", "faqRelated",
          "rawRelatedEvidence", "rulebookCandidates"]) {
          const candidates = [...(retrieved[bucket] ?? []), ...(evidence[bucket] ?? [])];
          evidence[bucket] = [...new Map(candidates.reverse().map(item => [item.id, item])).values()].reverse();
        }
        const promptBundle = buildRagRulingPromptBundle({
          userQuery: question, answerLocale: first.answerLocale, cardResolution: first.cardResolution, evidence, env,
        });
        const previousIds = new Set(first.promptBundle.allowedEvidenceIds);
        loopStatus = "no_new_admitted_evidence";
        if (promptBundle.allowedEvidenceIds.some(id => !previousIds.has(id))) {
          const { evidenceFingerprint, ...metadata } = first;
          const next = await finalize({ ...metadata, evidence, promptBundle, finalPromptSha256: hash(promptBundle.prompt) }, "supplement");
          result = next;
          loopStatus = "applied";
        }
      }
    } catch {
      loopStatus = "kept_baseline_after_failure";
    }
  }
  if (!result.shortAnswer?.trim()) throw new Error("Ruling returned no answer");
  const used = result.usedEvidence ?? [];
  const cited = used.filter(e => e.id && (result.shortAnswer.includes(e.id) || (e.title && result.shortAnswer.includes(e.title))));
  timings.total = Math.round(performance.now() - startedAt);
  console.info(JSON.stringify({ event: "ruling_timings", revision: pointer.revision, status: loopStatus,
    timings, modelStages: trace.map(({ stage, elapsed_ms }) => ({ stage, elapsed_ms })) }));
  return {
    answer: result.shortAnswer,
    evidence: cited.map(e => ({ evidence_id: e.id, title: e.title || e.id,
      text: [e.answer || e.text || e.question, e.sourceUrl].filter(Boolean).join("\n") })),
    agent_trace: trace,
    timings_ms: timings,
    agent_coverage: { route: "reference_rag_loop", status: loopStatus, corpus_revision: pointer.revision,
      estimated_cost_usd: trace.every(stage => stage.usage) ? cost : undefined },
  };
}

const send = (reply, status, data) => {
  reply.writeHead(status, { "content-type": "application/json; charset=utf-8" });
  reply.end(JSON.stringify(data));
};
let active = 0;
createServer(async (request, reply) => {
  if (request.method === "GET" && request.url === "/") {
    return send(reply, 200, { route: "reference_rag_loop", corpus_revision: pointer.revision, model });
  }
  if (request.method !== "POST" || request.url !== "/api/adjudicate") return send(reply, 404, {});
  if (active >= 2) return send(reply, 503, { error: "Ruling service busy" });
  active++;
  const controller = new AbortController();
  reply.on("close", () => controller.abort());
  try {
    const chunks = [];
    let size = 0;
    for await (const chunk of request) {
      size += chunk.length;
      if (size > 65536) return send(reply, 413, {});
      chunks.push(chunk);
    }
    const { scenario } = JSON.parse(Buffer.concat(chunks).toString("utf8"));
    if (typeof scenario !== "string" || !scenario.trim() || scenario.length > 8000) return send(reply, 400, {});
    send(reply, 200, await adjudicate(scenario.trim(), AbortSignal.any([controller.signal, AbortSignal.timeout(280000)])));
  } catch (error) {
    console.warn("Ruling request failed:", error.name, /^OpenAI HTTP \d+$/.test(error.message) ? error.message : "");
    if (!reply.destroyed) send(reply, 502, { error: "Ruling request failed" });
  } finally {
    active--;
  }
}).listen(Number(process.env.YGO_RULING_PORT || 7863), "127.0.0.1");
