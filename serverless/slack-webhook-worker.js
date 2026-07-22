// Slack Events API を受け取り、スレッド返信を GitHub の repository_dispatch(slack_reply)へ
// 中継する Cloudflare Worker(無料枠で動作)。
//
// 役割:
//  - Slack の URL 検証(url_verification)に応答
//  - 署名(SLACK_SIGNING_SECRET)を検証
//  - スレッドへの人間の返信のみを GitHub Actions に転送(bot発言・非返信は無視)
//  - Slack の 3 秒ルールを守るため、200 を即返しし転送は waitUntil で非同期実行
//
// 必要な環境変数(wrangler secret put で設定):
//  SLACK_SIGNING_SECRET   : Slack アプリの Signing Secret
//  GITHUB_DISPATCH_TOKEN  : repository_dispatch を叩ける PAT
//                           (classic=repo スコープ / fine-grained=Contents: Read and write)
//  GITHUB_REPO            : "sotaurabe/arxiv-research-digest"
//  SLACK_CHANNEL_ID       : 監視するチャンネルID(任意。設定すると他チャンネルを無視)

export default {
  async fetch(request, env, ctx) {
    if (request.method !== "POST") {
      return new Response("ok", { status: 200 });
    }

    const rawBody = await request.text();
    const timestamp = request.headers.get("x-slack-request-timestamp") || "";
    const signature = request.headers.get("x-slack-signature") || "";

    // 署名検証(リプレイ対策込み)
    if (!(await verifySlackSignature(env.SLACK_SIGNING_SECRET, timestamp, rawBody, signature))) {
      return new Response("invalid signature", { status: 401 });
    }

    let payload;
    try {
      payload = JSON.parse(rawBody);
    } catch {
      return new Response("bad json", { status: 400 });
    }

    // Slack の URL 検証
    if (payload.type === "url_verification") {
      return new Response(payload.challenge, {
        status: 200,
        headers: { "content-type": "text/plain" },
      });
    }

    // Slack のリトライは二重処理を避けるため転送しない(200 だけ返す)
    if (request.headers.get("x-slack-retry-num")) {
      return new Response("", { status: 200 });
    }

    if (payload.type === "event_callback" && payload.event) {
      const e = payload.event;
      const isHumanThreadReply =
        e.type === "message" &&
        !e.subtype &&
        !e.bot_id &&
        e.thread_ts &&
        e.thread_ts !== e.ts && // ルート投稿そのものは除外(返信のみ)
        (!env.SLACK_CHANNEL_ID || e.channel === env.SLACK_CHANNEL_ID);

      if (isHumanThreadReply) {
        ctx.waitUntil(
          dispatchToGitHub(env, {
            channel: e.channel,
            thread_ts: e.thread_ts,
            ts: e.ts,
            text: e.text || "",
          })
        );
      }
    }

    // 常に即 200(Slack の 3 秒タイムアウト対策)
    return new Response("", { status: 200 });
  },
};

async function verifySlackSignature(signingSecret, timestamp, body, signature) {
  if (!signingSecret || !timestamp || !signature) return false;
  // 5分より古いリクエストは拒否(リプレイ対策)
  const now = Math.floor(Date.now() / 1000);
  if (Math.abs(now - Number(timestamp)) > 60 * 5) return false;

  const base = `v0:${timestamp}:${body}`;
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(signingSecret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"]
  );
  const mac = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(base));
  const expected = "v0=" + [...new Uint8Array(mac)].map((b) => b.toString(16).padStart(2, "0")).join("");
  return timingSafeEqual(expected, signature);
}

function timingSafeEqual(a, b) {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

async function dispatchToGitHub(env, clientPayload) {
  const resp = await fetch(`https://api.github.com/repos/${env.GITHUB_REPO}/dispatches`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GITHUB_DISPATCH_TOKEN}`,
      Accept: "application/vnd.github+json",
      "Content-Type": "application/json",
      "User-Agent": "slack-arxiv-agent-worker",
      "X-GitHub-Api-Version": "2022-11-28",
    },
    body: JSON.stringify({ event_type: "slack_reply", client_payload: clientPayload }),
  });
  if (!resp.ok) {
    console.log("repository_dispatch failed", resp.status, await resp.text());
  }
}
