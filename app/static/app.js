// AI Staffing Assistant - Client-side Application Logic

let currentConversationId = null;
let currentUserRole = "manager";
let currentDashboardResources = [];
let sortCol = "current_allocation_pct";
let sortAsc = true;

// DOM Elements
const chatViewport = document.getElementById("messagesViewport");
const chatForm = document.getElementById("chatForm");
const chatInput = document.getElementById("chatInput");
const chipsList = document.getElementById("chipsList");
const userRoleSelect = document.getElementById("userRoleSelect");

// Initial Startup
document.addEventListener("DOMContentLoaded", () => {
  fetchModelsInfo();
  loadInitialGreeting();
  loadDashboardResources();
});

// Switch between Chat and Dashboard tabs
function switchTab(tabName) {
  document.querySelectorAll(".nav-tab").forEach(t => t.classList.remove("active"));
  document.querySelectorAll(".view-section").forEach(s => s.classList.remove("active"));

  if (tabName === "chat") {
    document.getElementById("tabChatBtn").classList.add("active");
    document.getElementById("chatSection").classList.add("active");
  } else {
    document.getElementById("tabDashboardBtn").classList.add("active");
    document.getElementById("dashboardSection").classList.add("active");
  }
}

// User Role change (Manager vs Recruiter)
function onRoleChange() {
  currentUserRole = userRoleSelect.value;
  // Re-fetch dashboard and refresh hourly cost column visibility
  loadDashboardResources();
  const thCost = document.getElementById("thHourlyCost");
  if (thCost) {
    thCost.textContent = currentUserRole === "manager" ? "Rate ($/hr) ↕" : "Rate (Hidden) ↕";
  }
}

// Theme toggle
function toggleTheme() {
  const isDark = document.body.classList.toggle("dark-theme");
  document.body.classList.toggle("light-theme", !isDark);
  document.getElementById("themeIcon").textContent = isDark ? "☀️" : "🌙";
}

// Fetch Models Info for persistent footer
async function fetchModelsInfo() {
  try {
    const res = await fetch("/api/models");
    const data = await res.json();
    
    // Update Conversational LLM
    document.getElementById("llmModelDisplay").textContent = `${data.llm_provider}: ${data.llm_model}`;
    document.getElementById("llmFreeBadge").textContent = data.llm_badge;

    // Update Decision Engine
    const jevDisplay = document.getElementById("jevModelDisplay");
    const jevBadge = document.getElementById("jevBadge");
    jevDisplay.textContent = `${data.decision_engine_name} (${data.decision_engine_model})`;

    if (data.is_mock) {
      jevBadge.textContent = "MOCK MODE - not real Jev";
      jevBadge.className = "badge badge-mock";
    } else {
      jevBadge.textContent = "Live Jev API";
      jevBadge.className = "badge badge-high";
    }
  } catch (err) {
    console.error("Failed to load models info:", err);
  }
}

// Initial Greeting Message
function loadInitialGreeting() {
  renderAssistantMessage({
    message: "Hello! I am your AI Staffing Assistant. Describe your project staffing needs (e.g., *'Find me a senior Python developer for a 3-month fintech project starting Oct 1'*), and I will filter active personnel, score them with calibrated TypeSafe decision logic, and highlight any low-confidence results for your review.",
    candidates: [],
    suggestion_chips: [
      "Find me a senior Python developer for a 3-month fintech project starting Oct 1",
      "Find a Lead React engineer for healthcare project",
      "Show me available QA testers with Selenium experience"
    ]
  });
}

// Clear chat
function clearChat() {
  currentConversationId = null;
  chatViewport.innerHTML = "";
  loadInitialGreeting();
}

// Chat Form Submit Handler
async function handleSend(e) {
  if (e) e.preventDefault();
  const msg = chatInput.value.trim();
  if (!msg) return;

  // Append user message
  renderUserMessage(msg);
  chatInput.value = "";

  // Render typing indicator
  const typingId = renderTypingIndicator();

  try {
    const payload = {
      message: msg,
      conversation_id: currentConversationId,
      user_role: currentUserRole
    };

    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    removeTypingIndicator(typingId);

    if (!res.ok) {
      const err = await res.json();
      renderErrorMessage(err.detail || "Error communicating with staffing orchestrator.");
      return;
    }

    const data = await res.json();
    currentConversationId = data.conversation_id;

    // Update Telemetry Panel
    updateTelemetry(data);

    // Render assistant message & candidates
    renderAssistantMessage(data);

  } catch (err) {
    removeTypingIndicator(typingId);
    renderErrorMessage(`Network error: ${err.message}`);
  }
}

function sendChip(chipText) {
  chatInput.value = chipText;
  handleSend();
}

// Telemetry Display in Footer
function updateTelemetry(data) {
  const latTotal = document.getElementById("latTotal");
  const latBreakdown = document.getElementById("latBreakdown");
  const tokenDisplay = document.getElementById("jevTokenCount");
  const costDisplay = document.getElementById("jevCostEstimate");

  latTotal.textContent = `${Math.round(data.total_latency_ms)}ms`;

  const lats = data.latencies || {};
  const sqlMs = Math.round(lats.sql_hard_constraint_filtering || 0);
  const jevMs = Math.round(lats.jev_decision_engine_scoring || 0);
  const llmMs = Math.round(lats.llm_intent_classification || 0);
  latBreakdown.textContent = `(LLM: ${llmMs}ms | SQL: ${sqlMs}ms | Jev: ${jevMs}ms)`;

  tokenDisplay.textContent = `${data.jev_tokens} tokens`;
  costDisplay.textContent = `$${data.jev_cost_usd.toFixed(6)} est.`;

  // Update Jev badge if fallback occurred
  const jevBadge = document.getElementById("jevBadge");
  if (data.is_fallback_scorer) {
    jevBadge.textContent = "Decision engine unavailable - using fallback rules";
    jevBadge.className = "badge badge-low";
  } else if (data.is_mock_jev) {
    jevBadge.textContent = "MOCK MODE - not real Jev";
    jevBadge.className = "badge badge-mock";
  } else {
    jevBadge.textContent = "Live Jev API";
    jevBadge.className = "badge badge-high";
  }
}

// Render User Message
function renderUserMessage(text) {
  const row = document.createElement("div");
  row.className = "message-row user";
  row.innerHTML = `<div class="bubble">${escapeHtml(text)}</div>`;
  chatViewport.appendChild(row);
  chatViewport.scrollTop = chatViewport.scrollHeight;
}

// Render Typing Indicator
function renderTypingIndicator() {
  const id = `typing-${Date.now()}`;
  const row = document.createElement("div");
  row.className = "message-row assistant";
  row.id = id;
  row.innerHTML = `
    <div class="bubble typing-bubble">
      <div class="typing-dot"></div>
      <div class="typing-dot"></div>
      <div class="typing-dot"></div>
    </div>
  `;
  chatViewport.appendChild(row);
  chatViewport.scrollTop = chatViewport.scrollHeight;
  return id;
}

function removeTypingIndicator(id) {
  const el = document.getElementById(id);
  if (el) el.remove();
}

// Render Assistant Message
function renderAssistantMessage(data) {
  const row = document.createElement("div");
  row.className = "message-row assistant";

  let candidatesHtml = "";
  if (data.candidates && data.candidates.length > 0) {
    candidatesHtml = `
      <div class="candidate-results-grid">
        ${data.candidates.map(c => renderCandidateCard(c, data.request_id)).join("")}
      </div>
    `;
  }

  // Warning banner if all top-3 were low confidence
  let warningBanner = "";
  if (data.is_clarifying_question && data.candidates && data.candidates.length > 0) {
    warningBanner = `
      <div class="alert-box" style="margin-bottom: 12px;">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
        <span><strong>Low-Confidence Alert:</strong> Multiple top candidates have uncertain skill alignment or pending commitments. Human review recommended.</span>
      </div>
    `;
  }

  row.innerHTML = `
    <div class="bubble">
      ${warningBanner}
      <div>${formatMarkdown(data.message)}</div>
      ${candidatesHtml}
    </div>
  `;

  chatViewport.appendChild(row);
  chatViewport.scrollTop = chatViewport.scrollHeight;

  // Render Suggestion Chips
  renderChips(data.suggestion_chips || []);
}

// Render Individual Candidate Card
function renderCandidateCard(cand, requestId) {
  // Confidence badge class
  let confClass = "badge-high";
  if (cand.confidence_level === "MODERATE") confClass = "badge-moderate";
  if (cand.confidence_level === "LOW") confClass = "badge-low";

  // Badges
  let badges = `<span class="badge ${confClass}">${cand.confidence_level} Confidence</span>`;
  if (cand.needs_pm_review) {
    badges += `<span class="badge badge-review">Needs PM Review</span>`;
  }
  if (cand.workload_risk) {
    badges += `<span class="badge badge-burnout">Workload Risk</span>`;
  }
  if (cand.is_tie) {
    badges += `<span class="badge badge-moderate">Too Close To Call</span>`;
  }

  // Rate Display
  const rateText = cand.hourly_cost ? `$${cand.hourly_cost}/hr` : `Rate: Hidden (PM only)`;

  return `
    <div class="candidate-card" id="card-${cand.resource_id}">
      <div class="candidate-card-header">
        <div class="cand-name-block">
          <h4>
            ${escapeHtml(cand.full_name)}
            <span style="font-size:0.8rem; font-weight:400; color:var(--text-dim);">(${cand.resource_id})</span>
          </h4>
          <div class="cand-meta">
            ${cand.seniority} ${cand.role} • ${cand.years_experience} yrs exp • ${cand.primary_domain} • ${cand.location}
          </div>
        </div>
        <div class="cand-badges">${badges}</div>
      </div>

      <div class="cand-metrics-row">
        <div class="cand-metric">
          <span class="lbl">Skill Score</span>
          <span class="val" style="color:var(--primary);">${cand.skill_score.toFixed(1)} / 4.0</span>
        </div>
        <div class="cand-metric">
          <span class="lbl">Current Alloc</span>
          <span class="val">${cand.current_allocation_pct}%</span>
        </div>
        <div class="cand-metric">
          <span class="lbl">Active Projects</span>
          <span class="val">${cand.concurrent_projects_count}</span>
        </div>
        <div class="cand-metric">
          <span class="lbl">Burnout Prob</span>
          <span class="val" style="color:${cand.burnout_prob >= 0.7 ? 'var(--warning)' : 'var(--text-main)'};">
            ${(cand.burnout_prob * 100).toFixed(0)}%
          </span>
        </div>
        <div class="cand-metric">
          <span class="lbl">Composite Rank</span>
          <span class="val" style="color:var(--success);">${(cand.final_score * 100).toFixed(1)}%</span>
        </div>
      </div>

      <div class="cand-explanation">
        ${escapeHtml(cand.explanation)}
      </div>

      <div class="cand-actions">
        <span class="cand-rate">${rateText}</span>
        <div class="cand-btn-group">
          <button class="btn-breakdown" onclick="showScoreBreakdown('${escapeHtml(JSON.stringify(cand))}')">Score Breakdown</button>
          <button class="btn-accept" id="btn-accept-${cand.resource_id}" onclick="submitFeedback('${requestId}', '${cand.resource_id}', 'accepted')">Accept</button>
          <button class="btn-reject" id="btn-reject-${cand.resource_id}" onclick="submitFeedback('${requestId}', '${cand.resource_id}', 'rejected')">Reject</button>
        </div>
      </div>
    </div>
  `;
}

// Submit Accept/Reject Feedback to DECISION_LOG
async function submitFeedback(requestId, candidateId, feedback) {
  try {
    const res = await fetch("/api/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        request_id: requestId,
        candidate_id: candidateId,
        feedback: feedback
      })
    });
    const data = await res.json();
    
    // Update card buttons
    const btnAcc = document.getElementById(`btn-accept-${candidateId}`);
    const btnRej = document.getElementById(`btn-reject-${candidateId}`);
    if (btnAcc && btnRej) {
      if (feedback === "accepted") {
        btnAcc.textContent = "✓ Accepted";
        btnAcc.disabled = true;
        btnRej.style.display = "none";
      } else {
        btnRej.textContent = "✕ Rejected";
        btnRej.disabled = true;
        btnAcc.style.display = "none";
      }
    }
  } catch (err) {
    alert("Feedback recording error: " + err.message);
  }
}

// Render Suggestion Chips
function renderChips(chips) {
  chipsList.innerHTML = "";
  if (!chips || chips.length === 0) {
    chips = ["Show someone cheaper", "Relax skill requirement", "Check availability"];
  }
  chips.forEach(chip => {
    const btn = document.createElement("button");
    btn.className = "chip-btn";
    btn.textContent = chip;
    btn.onclick = () => sendChip(chip);
    chipsList.appendChild(btn);
  });
}

// Render Error Message
function renderErrorMessage(msg) {
  const row = document.createElement("div");
  row.className = "message-row assistant";
  row.innerHTML = `<div class="bubble" style="background:var(--danger-bg); border-color:var(--danger); color:#fca5a5;">${escapeHtml(msg)}</div>`;
  chatViewport.appendChild(row);
  chatViewport.scrollTop = chatViewport.scrollHeight;
}

// =========================================
// Staffing Dashboard Logic
// =========================================
async function loadDashboardResources() {
  const role = document.getElementById("filterRole").value;
  const seniority = document.getElementById("filterSeniority").value;
  const domain = document.getElementById("filterDomain").value;
  const minExp = document.getElementById("filterExp").value;

  const params = new URLSearchParams();
  if (role) params.append("role", role);
  if (seniority) params.append("seniority", seniority);
  if (domain) params.append("domain", domain);
  if (minExp) params.append("min_exp", minExp);
  params.append("user_role", currentUserRole);
  params.append("limit", "150");

  try {
    const res = await fetch(`/api/resources?${params.toString()}`);
    const data = await res.json();
    currentDashboardResources = data.resources || [];
    renderDashboardTable();
  } catch (err) {
    console.error("Error loading resources:", err);
  }
}

function renderDashboardTable() {
  const tbody = document.getElementById("resourceTableBody");
  if (!currentDashboardResources.length) {
    tbody.innerHTML = `<tr><td colspan="9" class="loading-cell">No resources matching the selected filters.</td></tr>`;
    return;
  }

  // Sort resources
  currentDashboardResources.sort((a, b) => {
    let va = a[sortCol];
    let vb = b[sortCol];
    if (typeof va === "string") va = va.toLowerCase();
    if (typeof vb === "string") vb = vb.toLowerCase();
    if (va < vb) return sortAsc ? -1 : 1;
    if (va > vb) return sortAsc ? 1 : -1;
    return 0;
  });

  tbody.innerHTML = currentDashboardResources.map(r => {
    const alloc = r.current_allocation_pct || 0;
    let utilColor = "util-low";
    if (alloc >= 90) utilColor = "util-high";
    else if (alloc >= 70) utilColor = "util-mid";

    const costText = r.hourly_cost ? `$${r.hourly_cost}/hr` : "Hidden";
    const skillTags = (r.skills || []).map(s => `<span class="skill-tag">${s.normalized_skill}</span>`).join("");

    return `
      <tr>
        <td>
          <strong>${escapeHtml(r.full_name)}</strong>
          <div style="font-size:0.75rem; color:var(--text-dim);">${r.resource_id}</div>
        </td>
        <td>${r.role}</td>
        <td>${r.seniority}</td>
        <td>${r.years_experience}y</td>
        <td><span class="badge" style="background:rgba(255,255,255,0.05);">${r.primary_domain}</span></td>
        <td>${skillTags}</td>
        <td>
          <div class="util-bar-wrapper">
            <span>${alloc}%</span>
            <div class="util-bar-track">
              <div class="util-bar-fill ${utilColor}" style="width: ${Math.min(100, alloc)}%;"></div>
            </div>
          </div>
        </td>
        <td>${costText}</td>
        <td><span class="badge ${r.status === 'active' ? 'badge-high' : 'badge-low'}">${r.status}</span></td>
      </tr>
    `;
  }).join("");
}

function sortTable(col) {
  if (sortCol === col) {
    sortAsc = !sortAsc;
  } else {
    sortCol = col;
    sortAsc = true;
  }
  renderDashboardTable();
}

// =========================================
// Modals
// =========================================
function openBillingModal() {
  document.getElementById("billingModal").classList.add("open");
}

function closeBillingModal(e) {
  if (e && e.target !== e.currentTarget && !e.target.classList.contains("modal-close")) return;
  document.getElementById("billingModal").classList.remove("open");
}

function showScoreBreakdown(candJsonStr) {
  try {
    const cand = JSON.parse(candJsonStr);
    const b = cand.score_breakdown || {};
    document.getElementById("scoreModalTitle").textContent = `Score Breakdown: ${cand.full_name} (${cand.resource_id})`;

    const body = document.getElementById("scoreModalBody");
    body.innerHTML = `
      <p style="margin-bottom:16px; font-size:0.88rem; color:var(--text-muted);">
        Final Score Formula: <strong>w1*skill + w2*availability + w3*burnout_safety + w4*seniority - w5*cost</strong> = <strong>${(cand.final_score * 100).toFixed(1)}%</strong>
      </p>

      <div class="breakdown-row">
        <div class="breakdown-label">
          <span>Skill & Domain Fit (w1: 0.35)</span>
          <strong>+${(b.w1_skill || 0).toFixed(3)}</strong>
        </div>
        <div class="breakdown-bar"><div class="breakdown-progress" style="width: ${((b.w1_skill || 0) / 0.35) * 100}%;"></div></div>
      </div>

      <div class="breakdown-row">
        <div class="breakdown-label">
          <span>Capacity & Availability Fit (w2: 0.25)</span>
          <strong>+${(b.w2_availability || 0).toFixed(3)}</strong>
        </div>
        <div class="breakdown-bar"><div class="breakdown-progress" style="width: ${((b.w2_availability || 0) / 0.25) * 100}%; background:var(--success);"></div></div>
      </div>

      <div class="breakdown-row">
        <div class="breakdown-label">
          <span>Burnout Safety (w3: 0.20)</span>
          <strong>+${(b.w3_burnout || 0).toFixed(3)}</strong>
        </div>
        <div class="breakdown-bar"><div class="breakdown-progress" style="width: ${((b.w3_burnout || 0) / 0.20) * 100}%; background:var(--purple);"></div></div>
      </div>

      <div class="breakdown-row">
        <div class="breakdown-label">
          <span>Seniority Alignment (w4: 0.15)</span>
          <strong>+${(b.w4_seniority || 0).toFixed(3)}</strong>
        </div>
        <div class="breakdown-bar"><div class="breakdown-progress" style="width: ${((b.w4_seniority || 0) / 0.15) * 100}%;"></div></div>
      </div>

      <div class="breakdown-row">
        <div class="breakdown-label">
          <span>Cost Penalty (w5: 0.05)</span>
          <strong style="color:var(--danger);">${b.w5_cost_penalty ? '-' + b.w5_cost_penalty.toFixed(3) : '0.000'}</strong>
        </div>
        <div class="breakdown-bar"><div class="breakdown-progress" style="width: ${((b.w5_cost_penalty || 0) / 0.05) * 100}%; background:var(--danger);"></div></div>
      </div>
    `;

    document.getElementById("scoreModal").classList.add("open");
  } catch (err) {
    console.error("Error opening breakdown:", err);
  }
}

function closeScoreModal(e) {
  if (e && e.target !== e.currentTarget && !e.target.classList.contains("modal-close")) return;
  document.getElementById("scoreModal").classList.remove("open");
}

// Utility: Markdown simple formatter
function formatMarkdown(text) {
  if (!text) return "";
  let html = escapeHtml(text);
  // Bold
  html = html.replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");
  // Italic
  html = html.replace(/\*(.*?)\*/g, "<em>$1</em>");
  // Newlines
  html = html.replace(/\n/g, "<br>");
  return html;
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

// AI Call Logs Modal
async function openAiLogsModal() {
  document.getElementById("aiLogsModal").classList.add("open");
  await loadAiCallLogs();
}

function closeAiLogsModal(e) {
  if (e && e.target !== e.currentTarget && !e.target.classList.contains("modal-close")) return;
  document.getElementById("aiLogsModal").classList.remove("open");
}

async function loadAiCallLogs() {
  const container = document.getElementById("aiLogsModalBody");
  container.innerHTML = `<div style="text-align: center; padding: 20px; color: var(--text-muted);">Loading logged AI calls...</div>`;
  try {
    const res = await fetch("/api/logs/ai-calls?limit=25");
    const data = await res.json();
    if (!data.calls || data.calls.length === 0) {
      container.innerHTML = `<div style="text-align: center; padding: 20px; color: var(--text-muted);">No AI calls recorded yet. Send a query to see calls logged!</div>`;
      return;
    }
    let html = `<div style="margin-bottom: 12px; font-size: 0.85rem; color: var(--text-muted);">Showing latest <strong>${data.calls.length}</strong> of <strong>${data.total}</strong> recorded AI calls:</div>`;
    data.calls.forEach((c, idx) => {
      const isSuccess = c.status === "SUCCESS";
      const statusBadge = isSuccess 
        ? `<span class="badge badge-high">SUCCESS</span>` 
        : (c.status === "FALLBACK" ? `<span class="badge badge-mid">FALLBACK</span>` : `<span class="badge badge-low">${escapeHtml(c.status)}</span>`);
      
      const tokens = c.tokens ? `${c.tokens.total_tokens || 0} tokens` : "0 tokens";
      const cost = c.cost_usd ? `$${c.cost_usd.toFixed(6)}` : "$0.00";
      
      html += `
        <div style="background: rgba(255,255,255,0.03); border: 1px solid var(--border-color); border-radius: 8px; padding: 12px; margin-bottom: 10px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
            <div style="display: flex; align-items: center; gap: 8px;">
              ${statusBadge}
              <strong style="font-size: 0.95rem;">${escapeHtml(c.call_type)}</strong>
              <span style="font-size: 0.8rem; color: var(--text-muted);">[${escapeHtml(c.provider)} | ${escapeHtml(c.model)}]</span>
            </div>
            <div style="font-size: 0.8rem; color: var(--text-muted);">
              ${escapeHtml(c.timestamp.replace("T", " ").substring(0, 19))} | <strong>${c.latency_ms}ms</strong>
            </div>
          </div>
          <div style="display: flex; gap: 16px; font-size: 0.8rem; color: var(--text-secondary); margin-bottom: 8px;">
            <span><strong>Endpoint:</strong> <code>${escapeHtml(c.endpoint)}</code></span>
            <span><strong>Tokens:</strong> ${tokens}</span>
            <span><strong>Est Cost:</strong> ${cost}</span>
            <span><strong>Req ID:</strong> <code>${escapeHtml(c.request_id)}</code></span>
          </div>
          ${c.error ? `<div style="background: rgba(239,68,68,0.1); border-left: 3px solid #ef4444; padding: 6px 10px; margin-bottom: 8px; font-size: 0.8rem; color: #fca5a5;"><strong>Error:</strong> ${escapeHtml(c.error)}</div>` : ''}
          <details style="font-size: 0.8rem; margin-top: 6px;">
            <summary style="cursor: pointer; color: var(--accent-primary); font-weight: 500;">View Raw Request & Response Payloads</summary>
            <div style="margin-top: 8px; display: grid; grid-template-columns: 1fr 1fr; gap: 8px;">
              <div>
                <strong>Request Payload:</strong>
                <pre style="background: rgba(0,0,0,0.3); padding: 8px; border-radius: 6px; overflow-x: auto; max-height: 220px; font-size: 0.75rem;">${escapeHtml(JSON.stringify(c.request, null, 2))}</pre>
              </div>
              <div>
                <strong>Response Payload:</strong>
                <pre style="background: rgba(0,0,0,0.3); padding: 8px; border-radius: 6px; overflow-x: auto; max-height: 220px; font-size: 0.75rem;">${escapeHtml(JSON.stringify(c.response, null, 2))}</pre>
              </div>
            </div>
          </details>
        </div>
      `;
    });
    container.innerHTML = html;
  } catch (err) {
    container.innerHTML = `<div style="color: #ef4444; padding: 20px;">Failed to load AI logs: ${escapeHtml(err.message)}</div>`;
  }
}
