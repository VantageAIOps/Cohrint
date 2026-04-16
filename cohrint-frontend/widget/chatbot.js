(function () {
  "use strict";

  var CHATBOT_URL = window.VEGA_CHATBOT_URL || "https://chatbot.cohrint.com";
  var sessionId = null;
  var history = [];
  var isOpen = false;

  // ── DOM helpers ─────────────────────────────────────────────────────────────

  function makeEl(tag, id, className) {
    var node = document.createElement(tag);
    if (id) node.id = id;
    if (className) node.className = className;
    return node;
  }

  // ── Build widget ────────────────────────────────────────────────────────────

  // Launcher button with SVG chat-bubble icon
  var svgNS = "http://www.w3.org/2000/svg";
  var svg = document.createElementNS(svgNS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  var svgPath = document.createElementNS(svgNS, "path");
  svgPath.setAttribute(
    "d",
    "M12 2C6.477 2 2 6.477 2 12c0 1.89.525 3.66 1.438 5.168L2 22l4.832-1.438A9.956 9.956 0 0012 22c5.523 0 10-4.477 10-10S17.523 2 12 2z"
  );
  svg.appendChild(svgPath);

  var launcher = makeEl("button", "vega-launcher");
  launcher.setAttribute("aria-label", "Chat with Vega");
  launcher.appendChild(svg);

  // Panel header
  var headerName = makeEl("div", "vega-header-name");
  headerName.textContent = "Vega";
  var headerSub = makeEl("div", "vega-header-sub");
  headerSub.textContent = "Cohrint Assistant";
  var headerLeft = makeEl("div");
  headerLeft.appendChild(headerName);
  headerLeft.appendChild(headerSub);

  var closeBtn = makeEl("button", "vega-close");
  closeBtn.setAttribute("aria-label", "Close chat");
  closeBtn.textContent = "\u00d7";

  var header = makeEl("div", "vega-header");
  header.appendChild(headerLeft);
  header.appendChild(closeBtn);

  // Messages area
  var messagesEl = makeEl("div", "vega-messages");

  // Support ticket link
  var ticketBtn = makeEl("button", "vega-ticket-btn");
  ticketBtn.textContent = "Create a support ticket";

  // Input + send
  var input = makeEl("textarea", "vega-input");
  input.setAttribute("placeholder", "Ask Vega anything\u2026");
  input.setAttribute("rows", "2");
  var sendBtn = makeEl("button", "vega-send");
  sendBtn.textContent = "Send";
  var footer = makeEl("div", "vega-footer");
  footer.appendChild(input);
  footer.appendChild(sendBtn);

  // Assemble panel
  var panel = makeEl("div", "vega-panel");
  panel.appendChild(header);
  panel.appendChild(messagesEl);
  panel.appendChild(ticketBtn);
  panel.appendChild(footer);

  document.body.appendChild(launcher);
  document.body.appendChild(panel);

  // ── Helpers ─────────────────────────────────────────────────────────────────

  function addMessage(text, role) {
    var cls = "vega-msg " + (role === "user" ? "vega-msg-user" : "vega-msg-bot");
    var div = makeEl("div", null, cls);
    div.textContent = text;
    messagesEl.appendChild(div);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return div;
  }

  function showTyping() {
    var div = makeEl("div", null, "vega-msg vega-msg-bot");
    for (var i = 0; i < 3; i++) {
      div.appendChild(makeEl("span", null, "vega-typing-dot"));
    }
    messagesEl.appendChild(div);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return div;
  }

  // Greeting
  addMessage(
    "Hi! I\u2019m Vega, your Cohrint assistant. Ask me about your dashboard, pricing, or integrations.",
    "bot"
  );

  // ── Events ──────────────────────────────────────────────────────────────────

  launcher.addEventListener("click", function () {
    isOpen = !isOpen;
    if (isOpen) {
      panel.classList.add("vega-open");
      input.focus();
    } else {
      panel.classList.remove("vega-open");
    }
  });

  closeBtn.addEventListener("click", function () {
    isOpen = false;
    panel.classList.remove("vega-open");
  });

  // ── Inline ticket form (replaces window.prompt — CSP-safe, works in iframes) ─

  var ticketForm = null;

  function removeTicketForm() {
    if (ticketForm && ticketForm.parentNode) {
      ticketForm.parentNode.removeChild(ticketForm);
    }
    ticketForm = null;
  }

  function buildTicketForm() {
    removeTicketForm();

    var form = makeEl("div", "vega-ticket-form");
    form.style.cssText = "padding:12px;border-top:1px solid #3b3b5c;display:flex;flex-direction:column;gap:8px;";

    function field(placeholder, type) {
      var el = type === "textarea" ? makeEl("textarea") : makeEl("input");
      el.setAttribute("placeholder", placeholder);
      el.style.cssText = "background:#2a2a3e;border:1px solid #3b3b5c;border-radius:6px;color:#e2e8f0;padding:7px 10px;font-size:13px;outline:none;resize:none;width:100%;box-sizing:border-box;";
      if (type === "textarea") el.setAttribute("rows", "3");
      else el.setAttribute("type", type || "text");
      return el;
    }

    var subjectEl = field("Subject", "text");
    var bodyEl = field("Describe your issue\u2026", "textarea");
    var emailEl = field("Your email", "email");

    var btnRow = makeEl("div");
    btnRow.style.cssText = "display:flex;gap:8px;";

    var submitBtn = makeEl("button");
    submitBtn.textContent = "Send ticket";
    submitBtn.style.cssText = "background:#4f46e5;border:none;border-radius:6px;color:#fff;padding:7px 14px;cursor:pointer;font-size:13px;font-weight:500;flex:1;";

    var cancelBtn = makeEl("button");
    cancelBtn.textContent = "Cancel";
    cancelBtn.style.cssText = "background:#2a2a3e;border:1px solid #3b3b5c;border-radius:6px;color:#e2e8f0;padding:7px 14px;cursor:pointer;font-size:13px;";

    btnRow.appendChild(submitBtn);
    btnRow.appendChild(cancelBtn);

    form.appendChild(subjectEl);
    form.appendChild(bodyEl);
    form.appendChild(emailEl);
    form.appendChild(btnRow);

    cancelBtn.addEventListener("click", removeTicketForm);

    submitBtn.addEventListener("click", function () {
      var subject = subjectEl.value.trim();
      var msgBody = bodyEl.value.trim();
      var email = emailEl.value.trim();
      if (!subject || !msgBody || !email) {
        addMessage("Please fill in all three fields before sending.", "bot");
        return;
      }

      submitBtn.disabled = true;
      var tokenMatch = document.cookie.match(/session=([^;]+)/);
      var reqHeaders = { "Content-Type": "application/json" };
      if (tokenMatch) reqHeaders["Authorization"] = "Bearer " + tokenMatch[1];

      fetch(CHATBOT_URL + "/ticket", {
        method: "POST",
        headers: reqHeaders,
        body: JSON.stringify({ subject: subject, body: msgBody, email: email }),
      })
        .then(function (r) {
          removeTicketForm();
          addMessage(
            r.ok
              ? "Ticket submitted! We\u2019ll follow up at " + email + " soon."
              : "Couldn\u2019t submit ticket. Please email support@cohrint.com directly.",
            "bot"
          );
        })
        .catch(function () {
          removeTicketForm();
          addMessage("Couldn\u2019t submit ticket. Please email support@cohrint.com directly.", "bot");
        });
    });

    return form;
  }

  ticketBtn.addEventListener("click", function () {
    ticketForm = buildTicketForm();
    panel.insertBefore(ticketForm, footer);
    ticketForm.querySelector("input,textarea").focus();
  });

  function sendMessage() {
    var text = input.value.trim();
    if (!text) return;
    input.value = "";
    sendBtn.disabled = true;

    addMessage(text, "user");
    history.push({ role: "user", content: text });

    var typingEl = showTyping();
    var tokenMatch = document.cookie.match(/session=([^;]+)/);
    var orgId = document.body.getAttribute("data-org-id") || "unknown";
    var plan = document.body.getAttribute("data-plan") || "free";

    var reqHeaders = {
      "Content-Type": "application/json",
      "X-Org-Id": orgId,
      "X-Plan": plan,
    };
    if (tokenMatch) reqHeaders["Authorization"] = "Bearer " + tokenMatch[1];

    fetch(CHATBOT_URL + "/chat", {
      method: "POST",
      headers: reqHeaders,
      body: JSON.stringify({
        message: text,
        session_id: sessionId,
        history: history.slice(-6),
      }),
    })
      .then(function (r) {
        return r.json();
      })
      .then(function (data) {
        if (typingEl.parentNode) typingEl.parentNode.removeChild(typingEl);
        var reply =
          data && data.reply ? data.reply : "Sorry, something went wrong.";
        addMessage(reply, "bot");
        history.push({ role: "assistant", content: reply });
        if (data && data.session_id) sessionId = data.session_id;
      })
      .catch(function () {
        if (typingEl.parentNode) typingEl.parentNode.removeChild(typingEl);
        addMessage("Connection error. Please try again.", "bot");
      })
      .finally(function () {
        sendBtn.disabled = false;
      });
  }

  sendBtn.addEventListener("click", sendMessage);
  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });
})();
