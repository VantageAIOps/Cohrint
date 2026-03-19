/**
 * Email helper via Resend API.
 * Set RESEND_API_KEY as a Cloudflare Worker secret:
 *   wrangler secret put RESEND_API_KEY
 *
 * If the key is not set, emails are silently skipped (non-blocking).
 */

interface EmailOptions {
  to:      string;
  subject: string;
  html:    string;
}

export async function sendEmail(
  resendKey: string | undefined,
  opts: EmailOptions,
): Promise<void> {
  if (!resendKey) return; // silently skip if not configured

  const from = 'VantageAI <noreply@vantageaiops.com>';

  await fetch('https://api.resend.com/emails', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${resendKey}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ from, to: opts.to, subject: opts.subject, html: opts.html }),
  });
  // fire-and-forget — don't block the response on email delivery
}

// ── Email templates ───────────────────────────────────────────────────────────

export function memberInviteEmail(opts: {
  invitedBy: string;
  orgId:     string;
  orgName:   string;
  role:      string;
  scopeTeam: string | null;
  apiKey:    string;
  keyHint:   string;
}): { subject: string; html: string } {
  const dashUrl = `https://vantageaiops.com/app.html?api_key=${opts.apiKey}&org=${opts.orgId}`;
  return {
    subject: `You've been invited to ${opts.orgName} on VantageAI`,
    html: `
<div style="font-family:sans-serif;max-width:520px;margin:0 auto;padding:24px;color:#1a1a1a">
  <div style="margin-bottom:24px">
    <img src="https://vantageaiops.com/og-image.png" alt="VantageAI" style="height:28px">
  </div>
  <h2 style="font-size:20px;margin:0 0 8px">You've been invited</h2>
  <p style="color:#555;margin:0 0 20px"><strong>${opts.invitedBy}</strong> has added you to
    <strong>${opts.orgName}</strong> on VantageAI as <strong>${opts.role}</strong>
    ${opts.scopeTeam ? `(scoped to team: <strong>${opts.scopeTeam}</strong>)` : ''}.
  </p>

  <div style="background:#f4f4f4;border-radius:8px;padding:16px;margin-bottom:20px">
    <div style="font-size:11px;color:#888;margin-bottom:6px;text-transform:uppercase;letter-spacing:.06em">Your API key — shown once, store securely</div>
    <code style="font-size:13px;word-break:break-all;color:#111">${opts.apiKey}</code>
  </div>

  <div style="background:#fff8e1;border:1px solid #ffe082;border-radius:8px;padding:12px;font-size:13px;color:#795548;margin-bottom:20px">
    ⚠️ This key will not be shown again. Copy it now and store it in a password manager or environment variable.
  </div>

  <a href="${dashUrl}" style="display:inline-block;background:#00d4a1;color:#000;padding:11px 22px;border-radius:7px;text-decoration:none;font-weight:600;font-size:14px;margin-bottom:20px">
    Open Dashboard →
  </a>

  <div style="font-size:12px;color:#888;border-top:1px solid #eee;padding-top:16px;margin-top:8px">
    <strong>Quick start:</strong><br>
    <code style="font-size:11px">pip install vantageaiops</code> or
    <code style="font-size:11px">npm install vantageaiops</code><br><br>
    Questions? Reply to this email or visit <a href="https://vantageaiops.com/docs.html">docs</a>.
  </div>
</div>`,
  };
}

export function keyRecoveryEmail(opts: {
  orgId:    string;
  orgName:  string;
  keyHint:  string;
  isOwner:  boolean;
  memberHint?: string;
}): { subject: string; html: string } {
  return {
    subject: 'VantageAI — API key recovery',
    html: `
<div style="font-family:sans-serif;max-width:520px;margin:0 auto;padding:24px;color:#1a1a1a">
  <h2 style="font-size:20px;margin:0 0 12px">API key recovery</h2>
  <p style="color:#555;margin:0 0 16px">
    We received a recovery request for <strong>${opts.orgName}</strong> (org: <code>${opts.orgId}</code>).
  </p>

  <div style="background:#f4f4f4;border-radius:8px;padding:16px;margin-bottom:16px">
    <div style="font-size:11px;color:#888;margin-bottom:4px">Key hint</div>
    <code style="font-size:14px">${opts.keyHint}</code>
  </div>

  <p style="color:#555;font-size:14px">Your API key cannot be retrieved — it is stored as a one-way hash for security.</p>

  <p style="color:#555;font-size:14px">
    <strong>To get a new key:</strong><br>
    ${opts.isOwner
      ? `Sign in to the dashboard and go to <strong>Settings → Rotate API key</strong>, or ask your team admin.`
      : `Ask your org admin to revoke and re-issue your member key.`
    }
  </p>

  <a href="https://vantageaiops.com/app.html" style="display:inline-block;background:#00d4a1;color:#000;padding:11px 22px;border-radius:7px;text-decoration:none;font-weight:600;font-size:14px;margin-bottom:20px">
    Open Dashboard →
  </a>

  <div style="font-size:12px;color:#aaa;border-top:1px solid #eee;padding-top:16px;margin-top:8px">
    If you didn't request this, you can safely ignore this email.
  </div>
</div>`,
  };
}
