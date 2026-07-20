const byId = (id) => document.getElementById(id);

const out = {
  import: byId("importOut"),
  rules: byId("rulesOut"),
  accounts: byId("accountsOut"),
  process: byId("processOut"),
  unmatched: byId("unmatchedOut"),
  transactions: byId("transactionsOut"),
  assets: byId("assetsOut"),
  loans: byId("loansOut"),
  invoices: byId("invoicesOut"),
  invoiceDraft: byId("invoiceDraftLinesOut"),
  payroll: byId("payrollOut"),
  payrollEmployeeDetail: byId("payrollEmployeeDetailOut"),
  payrollDocVault: byId("payrollDocVaultOut"),
  taxBrackets: byId("taxBracketsOut"),
  reports: byId("reportsOut"),
  statements: byId("statementsOut"),
};

function cleanOptionalValue(value) {
  const v = String(value ?? "").trim();
  return v || null;
}

let activeReport = "trial";
let cachedAccounts = [];
let accountsTableVisible = false;
let payrollTaxBrackets = [];
let draftInvoiceLines = [];
let cachedCustomers = [];
let cachedInventoryItems = [];
let activeCompanyId = Number(localStorage.getItem("activeCompanyId") || 1);
let apiBase = localStorage.getItem("apiBase") || window.location.origin;
let runningBalanceVisible = false;

function buildApiUrl(path) {
  return new URL(path, apiBase);
}

function getApiCandidates() {
  const candidates = [];
  [window.location.origin, apiBase, "http://127.0.0.1:8000", "http://127.0.0.1:8001"].forEach((base) => {
    if (base && !candidates.includes(base)) {
      candidates.push(base);
    }
  });
  return candidates;
}

function normalizedCategory(category) {
  const c = String(category || "").trim().toLowerCase();
  if (["asset", "assets"].includes(c)) return "asset";
  if (["liability", "liabilities"].includes(c)) return "liability";
  if (["equity", "capital"].includes(c)) return "equity";
  if (["income", "revenue", "sales"].includes(c)) return "income";
  if (["expense", "expenses", "cost"].includes(c)) return "expense";
  return c;
}

function showToast(message) {
  const toast = byId("toast");
  toast.textContent = message;
  toast.classList.add("show");
  setTimeout(() => toast.classList.remove("show"), 1800);
}

function pretty(data) {
  return JSON.stringify(data, null, 2);
}

function formatBytes(bytes) {
  const n = Number(bytes || 0);
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(2)} MB`;
}

function writeOut(target, message) {
  if (!target) {
    console.error("Output target missing:", message);
    return;
  }
  target.textContent = message;
}

function renderUnmatchedTable(rows) {
  const container = byId("unmatchedOut");
  if (!container) {
    return;
  }

  if (!rows.length) {
    container.innerHTML = '<div class="empty-table">No unmatched transactions.</div>';
    return;
  }

  const header = `
    <thead>
      <tr>
        <th>ID</th>
        <th>Date</th>
        <th>Description</th>
        <th>Amount</th>
        <th>Status</th>
        <th>Account</th>
        <th>Actions</th>
      </tr>
    </thead>
  `;

  const accountOptions = [
    '<option value="">Choose account</option>',
    ...cachedAccounts.map(
      (acc) => `<option value="${acc.id}">${acc.code} - ${acc.name}</option>`
    ),
    '<option value="__create_new__">+ Create new account...</option>',
  ].join("");

  const bodyRows = rows
    .map((row) => {
      const amount = Number(row.amount || 0).toFixed(2);
      return `
        <tr>
          <td>${row.id ?? ""}</td>
          <td>${row.date ?? ""}</td>
          <td>${row.description ?? ""}</td>
          <td>${amount}</td>
          <td>${row.status ?? ""}</td>
          <td>
            <select class="table-select" id="reconAccount-${row.id}">
              ${accountOptions}
            </select>
          </td>
          <td>
            <div class="table-actions">
              <button class="btn btn-small" onclick="manualAllocate(${row.id}, false)">Allocate</button>
              <button class="btn btn-small btn-ghost" onclick="manualAllocate(${row.id}, true)">Allocate + Rule</button>
              <button class="btn btn-small btn-ghost" onclick="openCreateAccountForm()">Create Account</button>
            </div>
          </td>
        </tr>
      `;
    })
    .join("");

  container.innerHTML = `<table class="friendly-table">${header}<tbody>${bodyRows}</tbody></table>`;
}

function renderAccountsTable(rows) {
  const container = byId("accountsOut");
  if (!container) {
    return;
  }

  if (!rows.length) {
    container.innerHTML = '<div class="empty-table">No accounts found.</div>';
    return;
  }

  const header = `
    <thead>
      <tr>
        <th>ID</th>
        <th>Code</th>
        <th>Name</th>
        <th>Category</th>
        <th>VAT %</th>
      </tr>
    </thead>
  `;

  const bodyRows = rows
    .map((row) => `
      <tr>
        <td>${row.id ?? ""}</td>
        <td>${row.code ?? ""}</td>
        <td>${row.name ?? ""}</td>
        <td>${row.category ?? ""}</td>
        <td>${Number(row.vat_rate || 0).toFixed(2)}</td>
      </tr>
    `)
    .join("");

  container.innerHTML = `<table class="friendly-table">${header}<tbody>${bodyRows}</tbody></table>`;
}

function setAccountsTableVisibility(visible) {
  accountsTableVisible = visible;
  const container = byId("accountsOut");
  const btn = byId("toggleAccountsTableBtn");
  if (!container || !btn) {
    return;
  }

  if (visible) {
    container.classList.remove("is-hidden");
    btn.textContent = "Hide Accounts";
  } else {
    container.classList.add("is-hidden");
    btn.textContent = "Show Accounts";
  }
}

function openCreateAccountForm() {
  const section = byId("accountsCard");
  const input = byId("accountCode");
  if (section) {
    section.scrollIntoView({ behavior: "smooth", block: "start" });
  }
  if (input) {
    input.focus();
  }
}

function renderTransactionsTable(rows) {
  const container = byId("transactionsOut");
  if (!container) {
    return;
  }

  if (!rows.length) {
    container.innerHTML = '<div class="empty-table">No transactions found.</div>';
    return;
  }

  const header = `
    <thead>
      <tr>
        <th>ID</th>
        <th>Date</th>
        <th>Description</th>
        <th>Amount</th>
        <th>Type</th>
        <th>Status</th>
        <th>Account</th>
        <th>Edit Allocation</th>
        <th>Manage</th>
      </tr>
    </thead>
  `;

  const accountOptions = [
    '<option value="">Choose account</option>',
    ...cachedAccounts.map((acc) => `<option value="${acc.id}">${acc.code} - ${acc.name}</option>`),
  ].join("");

  const bodyRows = rows
    .map((row) => {
      const status = String(row.status || "").toLowerCase();
      const posted = status === "posted";
      return `
        <tr>
          <td>${row.id ?? ""}</td>
          <td>${row.txn_date ?? ""}</td>
          <td>${row.description ?? ""}</td>
          <td>${Number(row.amount || 0).toFixed(2)}</td>
          <td>${row.type_hint ?? ""}</td>
          <td><span class="status-chip status-${status}">${row.status ?? ""}</span></td>
          <td>${row.assigned_account_name ?? "-"}</td>
          <td>
            <div class="table-actions">
              <select class="table-select" id="txnAccount-${row.id}" ${posted ? "disabled" : ""}>
                ${accountOptions}
              </select>
              <button class="btn btn-small" onclick="reassignTransaction(${row.id})" ${posted ? "disabled" : ""}>Save</button>
            </div>
          </td>
          <td>
            <div class="table-actions">
              <button class="btn btn-small btn-ghost" onclick="editTransaction(${row.id})" ${posted ? "disabled" : ""}>Edit</button>
              <button class="btn btn-small btn-ghost" onclick="deleteTransaction(${row.id})" ${posted ? "disabled" : ""}>Delete</button>
            </div>
          </td>
        </tr>
      `;
    })
    .join("");

  container.innerHTML = `<table class="friendly-table">${header}<tbody>${bodyRows}</tbody></table>`;

  rows.forEach((row) => {
    const sel = byId(`txnAccount-${row.id}`);
    if (sel && row.assigned_account_id) {
      sel.value = String(row.assigned_account_id);
    }
  });
}

function renderLoansTable(rows) {
  const container = byId("loansOut");
  if (!container) {
    return;
  }
  if (!rows.length) {
    writeOut(out.loans, "No loans found.");
    return;
  }
  const table = renderRowsTable(
    ["ID", "Lender", "Principal", "Rate %", "Start Date", "Term (Months)", "Status", "Liability Account", "Interest Account"],
    rows.map((r) => [
      r.id,
      r.lender_name,
      Number(r.principal || 0).toFixed(2),
      Number(r.annual_interest_rate || 0).toFixed(2),
      r.start_date,
      r.term_months,
      r.status,
      r.liability_account_name,
      r.interest_expense_account_name,
    ])
  );
  byId("loansOut").innerHTML = table;
}

function renderAssetsTable(rows) {
  const container = byId("assetsOut");
  if (!container) {
    return;
  }
  if (!rows.length) {
    container.innerHTML = '<div class="empty-table">No assets found.</div>';
    return;
  }

  const table = renderRowsTable(
    [
      "ID",
      "Name",
      "Type",
      "Purchase Date",
      "Cost",
      "Accum. Depreciation",
      "Book Value",
      "Status",
      "Asset Account",
      "Dep. Expense Account",
    ],
    rows.map((r) => [
      r.id,
      r.name,
      r.asset_type,
      r.purchase_date,
      Number(r.cost || 0).toFixed(2),
      Number(r.accumulated_depreciation || 0).toFixed(2),
      Number(r.book_value || 0).toFixed(2),
      r.status,
      r.asset_account_name,
      r.depreciation_expense_account_name,
    ])
  );
  container.innerHTML = table;
}

function renderLoanHintsTable(rows) {
  const container = byId("transactionsOut");
  if (!container) return;
  if (!rows.length) {
    container.innerHTML = '<div class="empty-table">No loan/tax/interest hints found in imported transactions.</div>';
    return;
  }
  const table = renderRowsTable(
    ["Transaction ID", "Date", "Description", "Amount", "Status", "Suggestion"],
    rows.map((r) => [
      r.transaction_id,
      r.date || "",
      r.description || "",
      Number(r.amount || 0).toFixed(2),
      r.status || "",
      r.suggestion || "",
    ])
  );
  container.innerHTML = table;
}

function renderPayrollEmployeesTable(rows) {
  const container = byId("payrollOut");
  if (!container) {
    return;
  }
  if (!rows.length) {
    container.innerHTML = '<div class="empty-table">No payroll employees found.</div>';
    return;
  }

  const table = renderRowsTable(
    ["ID", "Code", "Name", "Gross Salary", "Tax %", "Active", "Profile", "Certificate"],
    rows.map((r) => [
      r.id,
      r.employee_code,
      r.full_name,
      Number(r.default_gross_salary || 0).toFixed(2),
      Number(r.tax_rate || 0).toFixed(2),
      r.active ? "Yes" : "No",
      `<button class="btn btn-small" onclick="viewPayrollEmployee(${r.id})">View</button>`,
      `<button class="btn btn-small btn-ghost" onclick="downloadEmploymentCertificate(${r.id})">Employment Cert</button>`,
    ])
  );
  container.innerHTML = `<div class="statement-caption">Payroll Employees</div>${table}`;
}

function renderPayrollEmployeeDetail(detail) {
  const container = out.payrollEmployeeDetail;
  if (!container) {
    return;
  }

  const emp = detail?.employee || {};
  const photo = String(emp.photo_url || "").trim();
  const avatar = photo
    ? `<img src="${photo}" alt="${emp.full_name || "Employee"}" style="width:96px;height:96px;border-radius:50%;object-fit:cover;border:2px solid #d8e6ff;" />`
    : `<div style="width:96px;height:96px;border-radius:50%;display:flex;align-items:center;justify-content:center;background:#edf4ff;color:#1d3557;font-weight:700;border:2px solid #d8e6ff;">${String(emp.full_name || "?").charAt(0).toUpperCase()}</div>`;

  const rows = (detail?.payroll_history || []).map((h) => `
    <tr>
      <td>${h.payroll_run_id}</td>
      <td>${h.period_label || ""}</td>
      <td>${h.pay_date || ""}</td>
      <td>${h.status || ""}</td>
      <td>${Number(h.gross_pay || 0).toFixed(2)}</td>
      <td>${Number(h.tax_amount || 0).toFixed(2)}</td>
      <td>${Number(h.net_pay || 0).toFixed(2)}</td>
      <td>
        <div class="table-actions">
          <button class="btn btn-small btn-ghost" onclick="downloadPayslip(${h.payroll_run_id}, ${emp.id})">Payslip</button>
          <button class="btn btn-small btn-ghost" onclick="downloadTaxCertificate(${h.payroll_run_id}, ${emp.id})">Tax Cert</button>
        </div>
      </td>
    </tr>
  `).join("");

  const historyTable = rows
    ? `<table class="friendly-table"><thead><tr><th>Run ID</th><th>Period</th><th>Pay Date</th><th>Status</th><th>Gross</th><th>PAYE</th><th>Net</th><th>Documents</th></tr></thead><tbody>${rows}</tbody></table>`
    : '<div class="empty-table">No payroll history found for this employee.</div>';

  const docs = detail?.documents || [];
  const docsRows = docs
    .map((d) => `
      <tr>
        <td>${d.id}</td>
        <td>${d.doc_type || ""}</td>
        <td>${d.title || ""}</td>
        <td>${d.original_filename || ""}</td>
        <td>${formatBytes(d.file_size)}</td>
        <td>${d.uploaded_at ? String(d.uploaded_at).slice(0, 10) : ""}</td>
        <td><button class="btn btn-small btn-ghost" onclick="downloadPayrollDocument(${d.id})">Download</button></td>
      </tr>
    `)
    .join("");

  const docsTable = docsRows
    ? `<table class="friendly-table"><thead><tr><th>Doc ID</th><th>Type</th><th>Title</th><th>File</th><th>Size</th><th>Uploaded</th><th>Action</th></tr></thead><tbody>${docsRows}</tbody></table>`
    : '<div class="empty-table">No employee documents uploaded yet.</div>';

  container.innerHTML = `
    <div class="statement-caption">Employee Profile</div>
    <div class="report-period" style="display:flex;gap:0.9rem;align-items:center;">
      ${avatar}
      <div>
        <div><b>${emp.full_name || ""}</b></div>
        <div>ID: ${emp.id || ""} | Employee No: ${emp.employee_code || ""}</div>
        <div>Gross: ${Number(emp.default_gross_salary || 0).toFixed(2)} | Tax: ${Number(emp.tax_rate || 0).toFixed(2)}% | Active: ${emp.active ? "Yes" : "No"}</div>
      </div>
    </div>
    <div class="profile-grid">
      <div><b>Position:</b> ${emp.position || "-"}</div>
      <div><b>Hire Date:</b> ${emp.hire_date || "-"}</div>
      <div><b>ID Number:</b> ${emp.id_number || "-"}</div>
      <div><b>Tax Number:</b> ${emp.tax_number || "-"}</div>
      <div><b>Email:</b> ${emp.email || "-"}</div>
      <div><b>Phone:</b> ${emp.phone || "-"}</div>
      <div><b>Bank Account:</b> ${emp.bank_account || "-"}</div>
      <div><b>NSSA:</b> ${emp.nssa_number || "-"}</div>
      <div><b>Pension:</b> ${emp.pension_number || "-"}</div>
    </div>
    <div class="statement-caption" style="margin-top:0.75rem;">Employee Documents</div>
    ${docsTable}
    <div class="statement-caption" style="margin-top:0.75rem;">Payroll History</div>
    ${historyTable}
  `;
}

function renderPayrollDocumentVault(rows) {
  const container = out.payrollDocVault;
  if (!container) {
    return;
  }
  if (!rows.length) {
    container.innerHTML = '<div class="empty-table">No documents found for this employee.</div>';
    return;
  }

  const body = rows
    .map(
      (d) => `
      <tr>
        <td>${d.id}</td>
        <td>${d.doc_type || ""}</td>
        <td>${d.title || ""}</td>
        <td>${d.original_filename || ""}</td>
        <td>${formatBytes(d.file_size)}</td>
        <td>${d.uploaded_at ? String(d.uploaded_at).slice(0, 10) : ""}</td>
        <td><button class="btn btn-small btn-ghost" onclick="downloadPayrollDocument(${d.id})">Download</button></td>
      </tr>
    `
    )
    .join("");

  container.innerHTML = `
    <div class="statement-caption">Employee Document Vault</div>
    <table class="friendly-table">
      <thead><tr><th>ID</th><th>Type</th><th>Title</th><th>Filename</th><th>Size</th><th>Uploaded</th><th>Action</th></tr></thead>
      <tbody>${body}</tbody>
    </table>
  `;
}

function renderPayrollRunsTable(rows) {
  const container = byId("payrollOut");
  if (!container) {
    return;
  }
  if (!rows.length) {
    container.innerHTML = '<div class="empty-table">No payroll runs found.</div>';
    return;
  }

  const header = `
    <thead>
      <tr>
        <th>ID</th>
        <th>Period</th>
        <th>Pay Date</th>
        <th>Status</th>
        <th>Gross</th>
        <th>PAYE</th>
        <th>NSSA</th>
        <th>Pension</th>
        <th>SDL</th>
        <th>Net</th>
        <th>Lines</th>
        <th>Actions</th>
      </tr>
    </thead>
  `;

  const bodyRows = rows
    .map((r) => `
      <tr>
        <td>${r.id}</td>
        <td>${r.period_label || ""}</td>
        <td>${r.pay_date || ""}</td>
        <td>${r.status || ""}</td>
        <td>${Number(r.total_gross || 0).toFixed(2)}</td>
        <td>${Number(r.total_tax || 0).toFixed(2)}</td>
        <td>${Number(r.total_nssa || 0).toFixed(2)}</td>
        <td>${Number(r.total_pension || 0).toFixed(2)}</td>
        <td>${Number(r.total_sdl || 0).toFixed(2)}</td>
        <td>${Number(r.total_net || 0).toFixed(2)}</td>
        <td>${r.line_count || 0}</td>
        <td>
          <div class="table-actions">
            <button class="btn btn-small" onclick="viewPayrollRun(${r.id})">View</button>
            <button class="btn btn-small btn-ghost" onclick="postPayrollRun(${r.id})" ${r.journal_entry_id ? "disabled" : ""}>Post</button>
            <button class="btn btn-small btn-ghost" onclick="payPayrollRun(${r.id})" ${r.payment_entry_id ? "disabled" : ""}>Pay</button>
            <button class="btn btn-small btn-ghost" onclick="downloadPayrollRun(${r.id}, 'pdf')">PDF</button>
            <button class="btn btn-small btn-ghost" onclick="downloadPayrollRun(${r.id}, 'csv')">CSV</button>
          </div>
        </td>
      </tr>
    `)
    .join("");

  container.innerHTML = `<table class="friendly-table">${header}<tbody>${bodyRows}</tbody></table>`;
}

function renderInvoiceDraftLines() {
  const container = out.invoiceDraft;
  if (!container) {
    return;
  }
  if (!draftInvoiceLines.length) {
    container.innerHTML = '<div class="empty-table">No invoice lines added yet.</div>';
    return;
  }

  const rows = draftInvoiceLines.map((ln, idx) => {
    const subtotal = Number(ln.quantity || 0) * Number(ln.unit_price || 0);
    const tax = subtotal * Number(ln.tax_rate || 0) / 100;
    const total = subtotal + tax;
    return [
      idx + 1,
      ln.description,
      Number(ln.quantity || 0).toFixed(2),
      Number(ln.unit_price || 0).toFixed(2),
      Number(ln.tax_rate || 0).toFixed(2),
      Number(total || 0).toFixed(2),
    ];
  });
  container.innerHTML = renderRowsTable(["#", "Description", "Qty", "Unit", "Tax %", "Total"], rows);
}

function renderInvoicesTable(rows) {
  const container = out.invoices;
  if (!container) {
    return;
  }
  if (!rows.length) {
    container.innerHTML = '<div class="empty-table">No invoices found.</div>';
    return;
  }

  const table = renderRowsTable(
    ["ID", "Number", "Customer", "Issue", "Due", "Status", "Total", "Actions"],
    rows.map((r) => [
      r.id,
      r.invoice_number,
      r.customer_name,
      r.issue_date,
      r.due_date,
      r.status,
      `${r.currency || "USD"} ${Number(r.total || 0).toFixed(2)}`,
      `<div class="table-actions"><button class="btn btn-small" onclick="viewInvoice(${r.id})">View</button><button class="btn btn-small btn-ghost" onclick="downloadInvoice(${r.id})">Download</button><button class="btn btn-small btn-ghost" onclick="sendInvoice(${r.id})" ${r.status === "paid" ? "disabled" : ""}>Send</button><button class="btn btn-small btn-ghost" onclick="markInvoicePaid(${r.id})" ${r.status === "paid" ? "disabled" : ""}>Mark Paid</button></div>`,
    ])
  );

  container.innerHTML = table;
}

function renderRowsTable(headers, rows) {
  const th = headers.map((h) => `<th>${h}</th>`).join("");
  const body = rows
    .map((row) => {
      const cells = Array.isArray(row) ? row : row.cells;
      const className = Array.isArray(row) ? "" : (row.className || "");
      return `<tr class="${className}">${cells.map((c) => `<td>${c ?? ""}</td>`).join("")}</tr>`;
    })
    .join("");
  return `<table class="friendly-table"><thead><tr>${th}</tr></thead><tbody>${body}</tbody></table>`;
}

function getReportPeriod() {
  const from = byId("reportsFromDate")?.value || "";
  const to = byId("reportsToDate")?.value || "";

  let label = "All periods";
  if (from && to) {
    label = `${from} to ${to}`;
  } else if (from) {
    label = `From ${from}`;
  } else if (to) {
    label = `Up to ${to}`;
  }

  return { from, to, label };
}

function getProjectionAssumptions() {
  const months = Number(byId("projectionMonths")?.value || 12);
  const inflowGrowth = Number(byId("projectionInflowGrowth")?.value || 0);
  const outflowGrowth = Number(byId("projectionOutflowGrowth")?.value || 0);
  const openingOverrideRaw = byId("projectionOpeningOverride")?.value;
  const openingOverride = openingOverrideRaw === "" || openingOverrideRaw == null ? null : Number(openingOverrideRaw);
  return { months, inflowGrowth, outflowGrowth, openingOverride };
}

function fmtAmt(value) {
  return Number(value || 0).toFixed(2);
}

function renderReportView(reportType, payload) {
  const container = byId("reportsOut");
  if (!container) {
    return;
  }
  const period = getReportPeriod();
  const periodBanner = `<div class="report-period">Reporting Period: ${period.label}</div>`;

  if (reportType === "trial") {
    const rows = payload.map((r) => [r.account_code, r.account_name, fmtAmt(r.debit), fmtAmt(r.credit), fmtAmt(r.net)]);
    container.innerHTML = `<div class="statement-caption">Statement: Trial Balance</div>${periodBanner}${renderRowsTable(["Code", "Account", "Debit", "Credit", "Net"], rows)}`;
    return;
  }

  if (reportType === "pnl") {
    const rows = [];
    rows.push({ className: "statement-row-section", cells: ["Revenue", "", "", ""] });
    (payload.income || []).forEach((r) => rows.push(["", r.code, r.name, fmtAmt(r.amount)]));
    rows.push({ className: "statement-row-subtotal", cells: ["", "", "Total Revenue", fmtAmt(payload.total_income)] });

    rows.push({ className: "statement-row-section", cells: ["Expenses", "", "", ""] });
    (payload.expenses || []).forEach((r) => rows.push(["", r.code, r.name, fmtAmt(r.amount)]));
    rows.push({ className: "statement-row-subtotal", cells: ["", "", "Total Expenses", fmtAmt(payload.total_expense)] });

    rows.push({ className: "statement-row-total", cells: ["", "", "Net Profit / (Loss)", fmtAmt(payload.net_profit)] });
    container.innerHTML = `<div class="statement-caption">Statement: Income Statement (Profit or Loss)</div>${periodBanner}${renderRowsTable(["Section", "Code", "Description", "Amount"], rows)}`;
    return;
  }

  if (reportType === "bs") {
    const rows = [];
    rows.push({ className: "statement-row-section", cells: ["Assets", "", "", ""] });
    rows.push({ className: "statement-row-section", cells: ["Current Assets", "", "", ""] });
    (payload.current_assets || []).forEach((r) => rows.push(["", r.code, r.name, fmtAmt(r.amount)]));
    rows.push({ className: "statement-row-subtotal", cells: ["", "", "Total Current Assets", fmtAmt(payload.total_current_assets)] });

    rows.push({ className: "statement-row-section", cells: ["Non-Current Assets", "", "", ""] });
    (payload.non_current_assets || []).forEach((r) => rows.push(["", r.code, r.name, fmtAmt(r.amount)]));
    rows.push({ className: "statement-row-subtotal", cells: ["", "", "Total Non-Current Assets", fmtAmt(payload.total_non_current_assets)] });
    rows.push({ className: "statement-row-total", cells: ["", "", "Total Assets", fmtAmt(payload.total_assets)] });

    rows.push({ className: "statement-row-section", cells: ["Liabilities", "", "", ""] });
    rows.push({ className: "statement-row-section", cells: ["Current Liabilities", "", "", ""] });
    (payload.current_liabilities || []).forEach((r) => rows.push(["", r.code, r.name, fmtAmt(r.amount)]));
    rows.push({ className: "statement-row-subtotal", cells: ["", "", "Total Current Liabilities", fmtAmt(payload.total_current_liabilities)] });

    rows.push({ className: "statement-row-section", cells: ["Non-Current Liabilities", "", "", ""] });
    (payload.non_current_liabilities || []).forEach((r) => rows.push(["", r.code, r.name, fmtAmt(r.amount)]));
    rows.push({ className: "statement-row-subtotal", cells: ["", "", "Total Non-Current Liabilities", fmtAmt(payload.total_non_current_liabilities)] });
    rows.push({ className: "statement-row-total", cells: ["", "", "Total Liabilities", fmtAmt(payload.total_liabilities)] });

    rows.push({ className: "statement-row-section", cells: ["Equity", "", "", ""] });
    (payload.equity || []).forEach((r) => rows.push(["", r.code, r.name, fmtAmt(r.amount)]));
    rows.push({ className: "statement-row-subtotal", cells: ["", "", "Retained Earnings", fmtAmt(payload.retained_earnings)] });
    rows.push({ className: "statement-row-total", cells: ["", "", "Total Equity", fmtAmt(payload.total_equity)] });

    rows.push({ className: "statement-row-total", cells: ["", "", "Assets = Liabilities + Equity", payload.balanced ? "Yes" : "No"] });
    container.innerHTML = `<div class="statement-caption">Statement: Statement of Financial Position (Balance Sheet)</div>${periodBanner}${renderRowsTable(["Section", "Code", "Description", "Amount"], rows)}`;
    return;
  }

  if (reportType === "cf") {
    const rows = [];
    rows.push({ className: "statement-row-section", cells: ["Operating Activities", "", "", "", ""] });
    (payload.operating_activities || []).forEach((r) => rows.push(["", r.date || "", r.description || "", r.account || "", fmtAmt(r.amount)]));
    rows.push({ className: "statement-row-subtotal", cells: ["", "", "Net Cash from Operating Activities", "", fmtAmt(payload.net_cash_from_operating)] });

    rows.push({ className: "statement-row-section", cells: ["Investing Activities", "", "", "", ""] });
    (payload.investing_activities || []).forEach((r) => rows.push(["", r.date || "", r.description || "", r.account || "", fmtAmt(r.amount)]));
    rows.push({ className: "statement-row-subtotal", cells: ["", "", "Net Cash from Investing Activities", "", fmtAmt(payload.net_cash_from_investing)] });

    rows.push({ className: "statement-row-section", cells: ["Financing Activities", "", "", "", ""] });
    (payload.financing_activities || []).forEach((r) => rows.push(["", r.date || "", r.description || "", r.account || "", fmtAmt(r.amount)]));
    rows.push({ className: "statement-row-subtotal", cells: ["", "", "Net Cash from Financing Activities", "", fmtAmt(payload.net_cash_from_financing)] });

    rows.push({ className: "statement-row-total", cells: ["", "", "Net Increase in Cash", "", fmtAmt(payload.net_increase_in_cash)] });
    rows.push({ className: "statement-row-subtotal", cells: ["", "", "Opening Cash Balance", "", fmtAmt(payload.opening_cash_balance)] });
    rows.push({ className: "statement-row-total", cells: ["", "", "Closing Cash Balance", "", fmtAmt(payload.closing_cash_balance)] });
    container.innerHTML = `<div class="statement-caption">Statement: Statement of Cash Flows</div>${periodBanner}${renderRowsTable(["Section", "Date", "Description", "Account", "Amount"], rows)}`;
    return;
  }

  if (reportType === "cfp") {
    const assumptions = payload.assumptions || {};
    const caption = `<div class="statement-caption">Statement: Cash Flow Projection</div>`;
    const assumptionsHtml = `
      <div class="report-period">
        Forecast Months: ${assumptions.months ?? ""} | Avg Inflows: ${fmtAmt(assumptions.avg_monthly_inflows)} |
        Avg Outflows: ${fmtAmt(assumptions.avg_monthly_outflows)} | Inflow Growth %: ${fmtAmt(assumptions.inflow_growth_pct)} |
        Outflow Growth %: ${fmtAmt(assumptions.outflow_growth_pct)}
      </div>
    `;
    const assumptionsBreakdownHtml = `
      <div class="report-period">
        Avg Income Inflows: ${fmtAmt(assumptions.avg_income_inflows)} | Avg Other Inflows: ${fmtAmt(assumptions.avg_other_inflows)} |
        Avg Payroll: ${fmtAmt(assumptions.avg_payroll_expenses)} | Avg OpEx: ${fmtAmt(assumptions.avg_operating_expenses)} |
        Avg Tax: ${fmtAmt(assumptions.avg_tax_expenses)} | Avg Interest: ${fmtAmt(assumptions.avg_interest_expenses)} |
        Avg Capex: ${fmtAmt(assumptions.avg_capex_outflows)} | Avg Financing Out: ${fmtAmt(assumptions.avg_financing_outflows)}
      </div>
    `;
    const rows = (payload.projection || []).map((r) => [
      r.month,
      fmtAmt(r.opening_balance),
      fmtAmt(r.projected_income_inflows),
      fmtAmt(r.projected_other_inflows),
      fmtAmt(r.projected_inflows),
      fmtAmt(r.projected_payroll_expenses),
      fmtAmt(r.projected_operating_expenses),
      fmtAmt(r.projected_tax_expenses),
      fmtAmt(r.projected_interest_expenses),
      fmtAmt(r.projected_capex_outflows),
      fmtAmt(r.projected_financing_outflows),
      fmtAmt(r.projected_outflows),
      fmtAmt(r.projected_net_cash),
      fmtAmt(r.closing_balance),
    ]);
    container.innerHTML = `${caption}${periodBanner}${assumptionsHtml}${assumptionsBreakdownHtml}${renderRowsTable(["Month", "Opening", "Income In", "Other In", "Total In", "Payroll", "OpEx", "Tax", "Interest", "Capex", "Financing", "Total Out", "Net Cash", "Closing"], rows)}`;
    return;
  }

  const rows = [];
  payload.forEach((entry) => {
    (entry.lines || []).forEach((line) => {
      rows.push([
        entry.id,
        entry.entry_date,
        entry.memo,
        entry.source,
        line.account_code,
        line.account_name,
        Number(line.debit || 0).toFixed(2),
        Number(line.credit || 0).toFixed(2),
      ]);
    });
  });
  container.innerHTML = `<div class="statement-caption">Statement: General Ledger</div>${periodBanner}${renderRowsTable(["Entry #", "Date", "Memo", "Source", "Code", "Account", "Debit", "Credit"], rows)}`;
}

function renderRulesTable(rows) {
  const container = byId("rulesOut");
  if (!container) {
    return;
  }

  if (!rows.length) {
    container.innerHTML = '<div class="empty-table">No rules found.</div>';
    return;
  }

  const header = `
    <thead>
      <tr>
        <th>ID</th>
        <th>Name</th>
        <th>Keywords</th>
        <th>Account</th>
        <th>Priority</th>
        <th>Add Keyword</th>
      </tr>
    </thead>
  `;

  const bodyRows = rows
    .map((row) => {
      const keywords = (row.keywords || []).join(", ");
      return `
        <tr>
          <td>${row.id ?? ""}</td>
          <td>${row.name ?? ""}</td>
          <td>${keywords || "-"}</td>
          <td>${row.account_name || row.account_id || ""}</td>
          <td>${row.priority ?? ""}</td>
          <td>
            <div class="table-actions">
              <input id="ruleKw-${row.id}" class="inline-input" placeholder="new keyword" />
              <button class="btn btn-small" onclick="appendRuleKeyword(${row.id})">Add</button>
            </div>
          </td>
        </tr>
      `;
    })
    .join("");

  container.innerHTML = `<table class="friendly-table">${header}<tbody>${bodyRows}</tbody></table>`;
}

async function callApi(path, options = {}) {
  const timeoutMs = Number(options.timeoutMs || 60000);
  const { timeoutMs: _ignored, ...requestOptions } = options;
  let lastError = null;

  for (const base of getApiCandidates()) {
    const url = new URL(path, base);
    url.searchParams.set("company_id", String(activeCompanyId || 1));

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    const fetchOptions = {
      ...requestOptions,
      signal: controller.signal,
    };

    try {
      const response = await fetch(url.toString(), fetchOptions);
      const payload = await response.json().catch(() => ({}));

      if (!response.ok) {
        // If this base points to an older/incompatible server, try the next candidate.
        if (response.status === 404) {
          lastError = new Error(`Not found on ${base}`);
          continue;
        }
        const detail = payload?.detail || "Request failed";
        throw new Error(detail);
      }

      if (apiBase !== base) {
        apiBase = base;
        localStorage.setItem("apiBase", apiBase);
      }
      return payload;
    } catch (err) {
      lastError = err;
      const timedOut = err?.name === "AbortError";
      const networkError = err instanceof TypeError;
      if (!timedOut && !networkError) {
        break;
      }
    } finally {
      clearTimeout(timer);
    }
  }

  if (lastError?.name === "AbortError") {
    throw new Error(`Request timed out after ${Math.round(timeoutMs / 1000)}s. Try again or use a smaller file.`);
  }
  throw lastError || new Error("Request failed");
}

async function fetchCompaniesWithBase(base) {
  const response = await fetch(new URL("/companies", base).toString());
  const payload = await response.json().catch(() => null);
  return { ok: response.ok, payload };
}

async function ensureCompaniesApi() {
  const candidates = [];
  [apiBase, window.location.origin, "http://127.0.0.1:8001"].forEach((base) => {
    if (base && !candidates.includes(base)) {
      candidates.push(base);
    }
  });

  for (const base of candidates) {
    try {
      const result = await fetchCompaniesWithBase(base);
      if (result.ok && Array.isArray(result.payload)) {
        const switched = apiBase !== base;
        apiBase = base;
        localStorage.setItem("apiBase", apiBase);
        if (switched && base === "http://127.0.0.1:8001") {
          showToast("Connected to updated API on port 8001");
        }
        return result.payload;
      }
    } catch (err) {
      // Keep trying other candidates if one base is down.
    }
  }

  throw new Error("Company workspace is not available. Start/open the updated API on http://127.0.0.1:8001");
}

async function loadCompanies() {
  const companies = await ensureCompaniesApi();

  const select = byId("activeCompanyId");
  if (!select) {
    return;
  }

  select.innerHTML = "";
  companies.forEach((c) => {
    const opt = document.createElement("option");
    opt.value = String(c.id);
    opt.textContent = `${c.name} (ID ${c.id})`;
    select.appendChild(opt);
  });

  const available = new Set(companies.map((c) => Number(c.id)));
  if (!available.has(activeCompanyId) && companies.length) {
    activeCompanyId = Number(companies[0].id);
  }
  if (companies.length) {
    select.value = String(activeCompanyId);
  }
}

async function createCompany() {
  const input = byId("newCompanyName");
  const name = input?.value?.trim() || "";
  if (!name) {
    throw new Error("Enter a company name");
  }

  await ensureCompaniesApi();
  const response = await fetch(new URL("/companies", apiBase).toString(), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok || !payload || typeof payload.id !== "number") {
    throw new Error("Could not create company. Ensure updated API is running on port 8001.");
  }

  input.value = "";
  activeCompanyId = Number(payload.id);
  localStorage.setItem("activeCompanyId", String(activeCompanyId));
  await loadCompanies();
  await refreshCompanyContext();
  showToast("Company created and selected");
}

async function deleteCompany() {
  const selectedId = Number(byId("activeCompanyId")?.value || activeCompanyId || 0);
  if (!selectedId) {
    throw new Error("Select a company first");
  }
  if (selectedId === 1) {
    throw new Error("Default company cannot be deleted");
  }

  const selectedName = byId("activeCompanyId")?.selectedOptions?.[0]?.textContent || `ID ${selectedId}`;
  const ok = window.confirm(`Move company ${selectedName} to recycle bin?`);
  if (!ok) {
    return;
  }

  await callApi(`/companies/${selectedId}`, { method: "DELETE" });

  await loadCompanies();
  const newSelected = Number(byId("activeCompanyId")?.value || 1);
  activeCompanyId = newSelected;
  localStorage.setItem("activeCompanyId", String(activeCompanyId));
  await refreshCompanyContext();
  showToast("Company moved to recycle bin");
}

async function refreshCompanyContext() {
  await loadCompanyProfile();
  await loadAccounts();
  await loadCustomers().catch(() => {});
  await loadInventoryItems().catch(() => {});
  await loadRules();
  await loadBalanceSummary();
  await loadRunningBalance().catch(() => {});
  await loadPeriodLock().catch(() => {});
  await loadInvoices().catch(() => {});
  await loadPayrollEmployees().catch(() => {});
  await loadPayrollRuns().catch(() => {});
  await loadTaxBrackets().catch(() => {});
  await loadReport().catch(() => {});
}

async function seedAllData() {
  const payload = await callApi("/setup/seed-all", { method: "POST" });
  writeOut(out.process, pretty(payload));
  showToast("Whole project seeded");
  await refreshCompanyContext();
  await loadTransactions().catch(() => {});
  await loadLoans().catch(() => {});
  await loadAssets().catch(() => {});
  await loadUnmatched().catch(() => {});
}

function inferDateFormatFromSample(sample) {
  const value = String(sample || "").trim();
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return "yyyy-mm-dd";
  if (/^\d{4}\/\d{2}\/\d{2}$/.test(value)) return "yyyy/mm/dd";
  if (/^\d{2}-\d{2}-\d{4}$/.test(value)) return "dd-mm-yyyy";
  if (/^\d{2}\/\d{2}\/\d{4}$/.test(value)) {
    const [a, b] = value.split("/").map((x) => Number(x));
    if (a > 12) return "dd/mm/yyyy";
    if (b > 12) return "mm/dd/yyyy";
    return "dd/mm/yyyy";
  }
  return "";
}

function normalizeDateToIso(raw) {
  const value = String(raw || "").trim();
  if (!value) return "";
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return value;

  const slash = value.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
  if (slash) {
    const a = Number(slash[1]);
    const b = Number(slash[2]);
    const y = slash[3];
    const day = a > 12 ? a : b;
    const month = a > 12 ? b : a;
    return `${y}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
  }

  const dash = value.match(/^(\d{1,2})-(\d{1,2})-(\d{4})$/);
  if (dash) {
    const d = Number(dash[1]);
    const m = Number(dash[2]);
    const y = dash[3];
    return `${y}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
  }

  return value;
}

function buildImportSuggestions(errors) {
  const suggestions = [];
  const messages = errors.map((e) => String(e?.message || "").toLowerCase());
  const raws = errors.map((e) => (e?.raw && typeof e.raw === "object" ? e.raw : {}));

  const hasUnsupportedDate = messages.some((m) => m.includes("unsupported date format"));
  if (hasUnsupportedDate) {
    const dateSamples = errors
      .map((e) => {
        const msg = String(e?.message || "");
        const match = msg.match(/unsupported date format:\s*(.+)$/i);
        return match ? match[1].trim() : "";
      })
      .filter(Boolean);

    const inferred = inferDateFormatFromSample(dateSamples[0] || "");
    if (inferred) {
      suggestions.push(`Set Date format to '${inferred}' in Import settings.`);
    } else {
      suggestions.push("Set Date format manually in Import settings to match your CSV.");
    }
  }

  const hasMissingAmount = messages.some((m) => m.includes("missing amount columns"));
  if (hasMissingAmount) {
    const keys = new Set(raws.flatMap((r) => Object.keys(r || {})));
    const hasDebit = ["debit", "debits", "withdrawal", "money_out", "outflow", "payment", "payments"].some((k) => keys.has(k));
    const hasCredit = ["credit", "credits", "deposit", "deposits", "money_in", "inflow"].some((k) => keys.has(k));
    const hasAmount = ["amount", "transaction_amount", "amt"].some((k) => keys.has(k));

    if (hasDebit && hasCredit) {
      suggestions.push("Set Amount mode to 'Debit and Credit columns', and map Debit/Credit column names if needed.");
    } else if (hasAmount) {
      suggestions.push("Set Amount mode to 'Single amount column (+/-)' and map Amount column name.");
    } else {
      suggestions.push("Map Amount column, or map Debit and Credit columns in Import settings.");
    }
  }

  const hasMissingDate = messages.some((m) => m.includes("missing date column value"));
  if (hasMissingDate) {
    suggestions.push("Map the Date column name in Import settings (e.g., date, txn_date, value_date).\nIf your CSV has header spaces/hyphens, type it exactly as shown in file.");
  }

  if (suggestions.length === 0 && errors.length) {
    suggestions.push("Check delimiter/header names and use Import column mapping fields to match your CSV.");
  }

  return suggestions;
}

async function importBank() {
  writeOut(out.import, "Importing CSV... please wait.");
  const file = byId("bankFile").files[0];
  if (!file) {
    throw new Error("Select a CSV file first");
  }

  const form = new FormData();
  form.append("file", file);
  const importSettings = {
    date_format: byId("importDateFormat")?.value || "",
    amount_mode: byId("importAmountMode")?.value || "auto",
  };

  Object.entries(importSettings).forEach(([k, v]) => {
    if (v !== null && v !== "") {
      form.append(k, v);
    }
  });

  const payload = await callApi("/bank/import", {
    method: "POST",
    body: form,
    timeoutMs: 180000,
  });

  let message = `Imported: ${payload.imported || 0}\nDuplicates skipped: ${payload.skipped_duplicates || 0}\nInvalid rows: ${payload.skipped_invalid_rows || 0}`;
  const errors = Array.isArray(payload.errors) ? payload.errors : [];
  if (errors.length) {
    const preview = errors.slice(0, 15).map((e) => `- Row ${e.row}: ${e.message}`).join("\n");
    message += `\n\nErrors (first ${Math.min(errors.length, 15)} of ${errors.length}):\n${preview}`;

    const suggestions = buildImportSuggestions(errors);
    if (suggestions.length) {
      message += `\n\nSuggested fixes:\n${suggestions.map((s) => `- ${s}`).join("\n")}`;
    }
  }
  writeOut(out.import, message);

  if ((payload.imported || 0) > 0) {
    showToast("Statement imported");
  } else if ((payload.skipped_invalid_rows || 0) > 0) {
    showToast("Import failed: check CSV errors");
  } else {
    showToast("No new rows imported");
  }

  await loadBalanceSummary();
  await loadRunningBalance();
}

async function setOpeningBalance() {
  const useSuggestedDate = byId("openingBalanceUseSuggested")?.checked === true;
  let balance_date = normalizeDateToIso(byId("openingBalanceDate").value);
  const amount = Number(byId("openingBalanceAmount").value);
  const note = byId("openingBalanceNote").value.trim();

  if ((useSuggestedDate || !balance_date) && !Number.isNaN(amount)) {
    const summary = await callApi("/bank/balance-summary");
    if (summary?.suggested_opening_balance_date) {
      balance_date = normalizeDateToIso(summary.suggested_opening_balance_date);
      if (byId("openingBalanceDate")) {
        byId("openingBalanceDate").value = balance_date;
      }
    }
  }

  if (!balance_date || Number.isNaN(amount)) {
    throw new Error("Provide opening balance date and amount");
  }

  const payload = await callApi("/bank/opening-balance", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ balance_date, amount, note }),
  });
  writeOut(out.import, pretty(payload));
  showToast("Opening balance set");
  await loadBalanceSummary();
}

async function loadBalanceSummary() {
  const payload = await callApi("/bank/balance-summary");
  const lines = [
    "BANK BALANCE SUMMARY",
    "--------------------",
    `Opening Balance Date : ${payload.opening_balance_date || "Not set"}`,
    `Opening Balance      : ${Number(payload.opening_balance || 0).toFixed(2)}`,
    `Total Inflows        : ${Number(payload.total_inflows || 0).toFixed(2)}`,
    `Total Outflows       : ${Number(payload.total_outflows || 0).toFixed(2)}`,
    `Net Movement         : ${Number(payload.net_movement || 0).toFixed(2)}`,
    `Closing Balance      : ${Number(payload.closing_balance || 0).toFixed(2)}`,
  ];

  if (payload.suggested_opening_balance_date) {
    lines.push(`Suggested Open Date  : ${payload.suggested_opening_balance_date}`);
  }
  if (payload.warning) {
    lines.push("");
    lines.push(`Warning: ${payload.warning}`);
  }

  writeOut(out.import, lines.join("\n"));
}

async function loadRunningBalance() {
  const payload = await callApi("/bank/running-balance");
  const container = byId("runningBalanceOut");
  const btn = byId("loadRunningBalanceBtn");
  if (!container) {
    return;
  }

  const banner = payload.warning
    ? `<div class="report-period">${payload.warning}</div>`
    : "";

  const rows = (payload.rows || []).map((r) => [
    r.date || "",
    r.description || "",
    Number(r.amount || 0).toFixed(2),
    Number(r.running_balance || 0).toFixed(2),
  ]);

  const headerSummary = `
    <div class="report-period">
      Opening Date: ${payload.opening_balance_date || "Not set"} |
      Opening Balance: ${Number(payload.opening_balance || 0).toFixed(2)} |
      Closing Balance: ${Number(payload.closing_balance || 0).toFixed(2)}
      ${payload.suggested_opening_balance_date ? `| Suggested Opening Date: ${payload.suggested_opening_balance_date}` : ""}
    </div>
  `;

  if (!rows.length) {
    container.innerHTML = `${banner}${headerSummary}<div class="empty-table">No transactions imported yet.</div>`;
    container.classList.remove("is-hidden");
    runningBalanceVisible = true;
    if (btn) btn.textContent = "Hide Running Balance";
    return;
  }

  container.innerHTML = `${banner}${headerSummary}${renderRowsTable(["Date", "Description", "Amount", "Running Balance"], rows)}`;
  container.classList.remove("is-hidden");
  runningBalanceVisible = true;
  if (btn) btn.textContent = "Hide Running Balance";
}

async function toggleRunningBalance() {
  const container = byId("runningBalanceOut");
  const btn = byId("loadRunningBalanceBtn");
  if (!container) {
    return;
  }

  if (runningBalanceVisible && !container.classList.contains("is-hidden")) {
    container.classList.add("is-hidden");
    runningBalanceVisible = false;
    if (btn) btn.textContent = "Load Running Balance";
    return;
  }

  await loadRunningBalance();
}

async function addRule() {
  const name = byId("ruleName").value.trim();
  const keyword = byId("ruleKeyword").value.trim();
  const accountId = Number(byId("ruleAccountId").value);
  const priority = Number(byId("rulePriority").value || 100);

  if (!name || !keyword || !accountId) {
    throw new Error("Provide name, keyword, and account ID");
  }

  const payload = await callApi("/rules", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name,
      keyword,
      account_id: accountId,
      priority,
    }),
  });

  writeOut(out.process, pretty(payload));
  showToast("Rule added");
  await loadRules();
}

async function deleteRule() {
  const ruleId = Number(byId("deleteRuleId").value);
  if (!ruleId) {
    throw new Error("Enter a valid rule ID");
  }
  const payload = await callApi(`/rules/${ruleId}`, { method: "DELETE" });
  writeOut(out.process, pretty(payload));
  showToast("Rule deleted");
  await loadRules();
}

async function loadRules() {
  const payload = await callApi("/rules");
  renderRulesTable(payload);
}

async function appendRuleKeywordToRule(ruleId) {
  const input = byId(`ruleKw-${ruleId}`);
  const keyword = (input?.value || "").trim();
  if (!keyword) {
    throw new Error("Type a keyword to add");
  }

  await callApi(`/rules/${ruleId}/keywords`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ keyword }),
  });

  showToast("Keyword added to rule");
  await loadRules();
}

async function loadAccounts() {
  const payload = await callApi("/accounts");
  const select = byId("ruleAccountId");
  const manageSelect = byId("accountManageSelect");
  const txnAccountSelect = byId("txnAccountId");
  const txnAccountFilterSelect = byId("transactionAccountFilter");
  const assetAccountSelect = byId("assetAccountId");
  const assetDepSelect = byId("assetDepExpenseAccountId");
  const loanLiabilitySelect = byId("loanLiabilityAccountId");
  const loanInterestSelect = byId("loanInterestExpenseAccountId");
  const payrollExpenseSelect = byId("payrollExpenseAccountId");
  const payrollPayableSelect = byId("payrollPayableAccountId");
  const payrollTaxLiabilitySelect = byId("payrollTaxLiabilityAccountId");
  const payrollBankSelect = byId("payrollBankAccountId");
  const invoiceIncomeSelect = byId("invoiceIncomeAccountId");
  const selected = select.value;
  const manageSelected = manageSelect.value;
  const txnAccountSelected = txnAccountSelect?.value || "";
  const txnAccountFilterSelected = txnAccountFilterSelect?.value || "";
  const invoiceIncomeSelected = invoiceIncomeSelect?.value || "";

  select.innerHTML = '<option value="">Select account</option>';
  manageSelect.innerHTML = '<option value="">Select account to delete</option>';
  if (txnAccountSelect) txnAccountSelect.innerHTML = '<option value="">Assigned account (optional)</option>';
  if (txnAccountFilterSelect) txnAccountFilterSelect.innerHTML = '<option value="">All accounts</option>';
  assetAccountSelect.innerHTML = '<option value="">Asset account</option>';
  assetDepSelect.innerHTML = '<option value="">Depreciation expense account</option>';
  loanLiabilitySelect.innerHTML = '<option value="">Loan liability account</option>';
  loanInterestSelect.innerHTML = '<option value="">Interest expense account</option>';
  if (payrollExpenseSelect) payrollExpenseSelect.innerHTML = '<option value="">Payroll expense account</option>';
  if (payrollPayableSelect) payrollPayableSelect.innerHTML = '<option value="">Payroll payable account</option>';
  if (payrollTaxLiabilitySelect) payrollTaxLiabilitySelect.innerHTML = '<option value="">Tax liability account (optional)</option>';
  if (payrollBankSelect) payrollBankSelect.innerHTML = '<option value="">Payroll payment bank account</option>';
  if (invoiceIncomeSelect) invoiceIncomeSelect.innerHTML = '<option value="">Income account (optional)</option>';

  payload.forEach((account) => {
    const vatLabel = Number(account.vat_rate || 0).toFixed(2);
    const label = `${account.code} - ${account.name} (${account.category}, VAT ${vatLabel}%)`;

    const opt = document.createElement("option");
    opt.value = String(account.id);
    opt.textContent = label;
    select.appendChild(opt);

    const opt2 = document.createElement("option");
    opt2.value = String(account.id);
    opt2.textContent = label;
    manageSelect.appendChild(opt2);

    if (txnAccountSelect) {
      const txnOpt = document.createElement("option");
      txnOpt.value = String(account.id);
      txnOpt.textContent = label;
      txnAccountSelect.appendChild(txnOpt);
    }

    if (txnAccountFilterSelect) {
      const txnFilterOpt = document.createElement("option");
      txnFilterOpt.value = String(account.id);
      txnFilterOpt.textContent = label;
      txnAccountFilterSelect.appendChild(txnFilterOpt);
    }

    const cat = normalizedCategory(account.category);

    if (cat === "asset") {
      const optAsset = document.createElement("option");
      optAsset.value = String(account.id);
      optAsset.textContent = label;
      assetAccountSelect.appendChild(optAsset);

      if (payrollBankSelect) {
        const optPayrollBank = document.createElement("option");
        optPayrollBank.value = String(account.id);
        optPayrollBank.textContent = label;
        payrollBankSelect.appendChild(optPayrollBank);
      }
    }

    if (cat === "expense") {
      const optDep = document.createElement("option");
      optDep.value = String(account.id);
      optDep.textContent = label;
      assetDepSelect.appendChild(optDep);

      const optInterest = document.createElement("option");
      optInterest.value = String(account.id);
      optInterest.textContent = label;
      loanInterestSelect.appendChild(optInterest);

      if (payrollExpenseSelect) {
        const optPayrollExpense = document.createElement("option");
        optPayrollExpense.value = String(account.id);
        optPayrollExpense.textContent = label;
        payrollExpenseSelect.appendChild(optPayrollExpense);
      }
    }

    if (cat === "liability") {
      const optLiab = document.createElement("option");
      optLiab.value = String(account.id);
      optLiab.textContent = label;
      loanLiabilitySelect.appendChild(optLiab);

      if (payrollPayableSelect) {
        const optPayrollPayable = document.createElement("option");
        optPayrollPayable.value = String(account.id);
        optPayrollPayable.textContent = label;
        payrollPayableSelect.appendChild(optPayrollPayable);
      }

      if (payrollTaxLiabilitySelect) {
        const optPayrollTax = document.createElement("option");
        optPayrollTax.value = String(account.id);
        optPayrollTax.textContent = label;
        payrollTaxLiabilitySelect.appendChild(optPayrollTax);
      }
    }

    if (cat === "income" && invoiceIncomeSelect) {
      const optInvoiceIncome = document.createElement("option");
      optInvoiceIncome.value = String(account.id);
      optInvoiceIncome.textContent = label;
      invoiceIncomeSelect.appendChild(optInvoiceIncome);
    }
  });

  if (selected) {
    select.value = selected;
  }
  if (manageSelected) {
    manageSelect.value = manageSelected;
  }
  if (txnAccountSelected && txnAccountSelect) {
    txnAccountSelect.value = txnAccountSelected;
  }
  if (txnAccountFilterSelected && txnAccountFilterSelect) {
    txnAccountFilterSelect.value = txnAccountFilterSelected;
  }
  if (invoiceIncomeSelected && invoiceIncomeSelect) {
    invoiceIncomeSelect.value = invoiceIncomeSelected;
  }

  cachedAccounts = payload;
  if (accountsTableVisible) {
    renderAccountsTable(payload);
  }
  writeOut(out.rules, `Accounts loaded: ${payload.length}`);
}

async function reassignTransactionAccount(transactionId) {
  const selector = byId(`txnAccount-${transactionId}`);
  const accountId = Number(selector?.value || 0);
  if (!accountId) {
    throw new Error("Choose an account first");
  }

  await callApi(`/bank/transactions/${transactionId}/assign`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ account_id: accountId, create_rule: false, auto_rule: false, priority: 100 }),
  });

  showToast("Transaction allocation updated");
  await refreshTransactionDerivedViews();
}

async function refreshUnmatchedIfVisible() {
  const container = byId("unmatchedOut");
  if (!container || container.classList.contains("is-hidden")) {
    return;
  }
  const payload = await callApi("/bookkeeping/documents");
  renderUnmatchedTable(payload.unmatched_transactions || []);
}

async function refreshTransactionDerivedViews() {
  await loadTransactions();
  await refreshUnmatchedIfVisible().catch(() => {});
  await loadBalanceSummary().catch(() => {});
  await loadRunningBalance().catch(() => {});
}

function clearTransactionForm() {
  const today = new Date().toISOString().slice(0, 10);
  byId("txnEditId").value = "";
  byId("txnDate").value = byId("txnDate").value || today;
  byId("txnDescription").value = "";
  byId("txnAmount").value = "";
  byId("txnCurrency").value = byId("txnCurrency").value || "USD";
  byId("txnReference").value = "";
  if (byId("txnAccountId")) byId("txnAccountId").value = "";
}

function getManualTransactionPayload() {
  const txn_date = byId("txnDate")?.value;
  const description = byId("txnDescription")?.value?.trim() || "";
  const amount = Number(byId("txnAmount")?.value);
  const currency = (byId("txnCurrency")?.value?.trim() || "USD").toUpperCase();
  const reference = byId("txnReference")?.value?.trim() || "";
  const assignedRaw = Number(byId("txnAccountId")?.value || 0);
  const assigned_account_id = assignedRaw > 0 ? assignedRaw : null;

  if (!txn_date || !description || Number.isNaN(amount)) {
    throw new Error("Provide date, description, and amount");
  }

  return { txn_date, description, amount, currency, reference, assigned_account_id };
}

async function addManualTransaction() {
  const payload = getManualTransactionPayload();
  await callApi("/bank/transactions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  showToast("Transaction added");
  clearTransactionForm();
  await refreshTransactionDerivedViews();
}

async function updateManualTransaction() {
  const txnId = Number(byId("txnEditId")?.value || 0);
  if (!txnId) {
    throw new Error("Select a transaction to edit first");
  }
  const payload = getManualTransactionPayload();
  await callApi(`/bank/transactions/${txnId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  showToast("Transaction updated");
  clearTransactionForm();
  await refreshTransactionDerivedViews();
}

async function editTransactionById(transactionId) {
  const rows = await callApi("/bank/transactions");
  const txn = (rows || []).find((x) => Number(x.id) === Number(transactionId));
  if (!txn) {
    throw new Error("Transaction not found");
  }
  byId("txnEditId").value = String(txn.id);
  byId("txnDate").value = txn.txn_date || "";
  byId("txnDescription").value = txn.description || "";
  byId("txnAmount").value = String(Number(txn.amount || 0));
  byId("txnCurrency").value = txn.currency || "USD";
  byId("txnReference").value = txn.reference || "";
  if (byId("txnAccountId")) {
    byId("txnAccountId").value = txn.assigned_account_id ? String(txn.assigned_account_id) : "";
  }
  byId("transactionsCard")?.scrollIntoView({ behavior: "smooth", block: "start" });
  byId("txnDescription")?.focus();
}

async function deleteTransactionById(transactionId) {
  await callApi(`/bank/transactions/${transactionId}`, { method: "DELETE" });
  showToast("Transaction deleted");
  const currentEditId = Number(byId("txnEditId")?.value || 0);
  if (currentEditId === Number(transactionId)) {
    clearTransactionForm();
  }
  await refreshTransactionDerivedViews();
}

async function loadAndShowAccounts() {
  await loadAccounts();
  renderAccountsTable(cachedAccounts);
  setAccountsTableVisibility(true);
}

function toggleAccountsTable() {
  if (accountsTableVisible) {
    setAccountsTableVisibility(false);
    return;
  }

  if (cachedAccounts.length) {
    renderAccountsTable(cachedAccounts);
    setAccountsTableVisibility(true);
    return;
  }

  loadAndShowAccounts().catch((err) => {
    writeOut(out.accounts, `Error: ${err.message || err}`);
  });
}

async function manualAllocateTxn(transactionId, createRule) {
  const selector = byId(`reconAccount-${transactionId}`);
  const rawValue = selector?.value || "";
  if (rawValue === "__create_new__") {
    openCreateAccountForm();
    throw new Error("Create the new account first, then come back and allocate");
  }

  const accountId = Number(rawValue || 0);
  if (!accountId) {
    throw new Error("Choose an account first");
  }

  const txn = await callApi("/bank/transactions");
  const found = txn.find((x) => x.id === transactionId);

  const payload = {
    account_id: accountId,
    create_rule: Boolean(createRule),
    auto_rule: true,
    rule_name: found ? `Rule - ${found.description}` : `Rule - TXN ${transactionId}`,
    rule_keyword: found ? found.description : `txn-${transactionId}`,
    priority: 100,
  };

  await callApi(`/bank/transactions/${transactionId}/assign`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  showToast(createRule ? "Allocated and rule created" : "Allocated");
  await loadUnmatched();
  await loadTransactions();
  if (createRule) {
    await loadRules();
  }
}

async function createAccount() {
  const code = byId("accountCode").value.trim();
  const name = byId("accountName").value.trim();
  const category = byId("accountCategory").value;
  const vatRate = Number(byId("accountVatRate").value || 0);

  if (!code || !name || !category) {
    throw new Error("Provide account code, name, and category");
  }
  if (Number.isNaN(vatRate) || vatRate < 0 || vatRate > 100) {
    throw new Error("VAT rate must be between 0 and 100");
  }

  const payload = await callApi("/accounts", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code, name, category, vat_rate: vatRate }),
  });

  showToast("Account added");
  byId("accountCode").value = "";
  byId("accountName").value = "";
  byId("accountVatRate").value = "0";
  await loadAccounts();
}

async function deleteAccount() {
  const accountId = Number(byId("accountManageSelect").value);
  if (!accountId) {
    throw new Error("Select an account to delete");
  }

  const payload = await callApi(`/accounts/${accountId}`, { method: "DELETE" });
  writeOut(out.rules, pretty(payload));
  showToast("Account deleted");
  await loadAccounts();
}

function buildTransactionFilterQuery() {
  const params = new URLSearchParams();
  const q = byId("transactionSearch")?.value?.trim() || "";
  const accountId = Number(byId("transactionAccountFilter")?.value || 0);
  const fromDate = byId("transactionFromDate")?.value || "";
  const toDate = byId("transactionToDate")?.value || "";

  if (q) {
    params.set("q", q);
  }
  if (accountId > 0) {
    params.set("account_id", String(accountId));
  }
  if (fromDate) {
    params.set("from_date", fromDate);
  }
  if (toDate) {
    params.set("to_date", toDate);
  }

  return params.toString();
}

async function loadTransactions() {
  writeOut(out.transactions, "Loading transactions...");
  const query = buildTransactionFilterQuery();
  const path = query ? `/bank/transactions?${query}` : "/bank/transactions";
  const payload = await callApi(path, { timeoutMs: 90000 });
  renderTransactionsTable(payload);
  const total = (payload || []).reduce((sum, row) => sum + Number(row.amount || 0), 0);
  const totalEl = byId("transactionsTotal");
  if (totalEl) {
    totalEl.textContent = `Total: ${total.toFixed(2)}`;
  }
  const accountSelect = byId("transactionAccountFilter");
  const summaryEl = byId("transactionsSearchSummary");
  if (summaryEl) {
    const accountLabel = accountSelect?.selectedOptions?.[0]?.textContent || "All accounts";
    summaryEl.textContent = `Showing ${payload.length || 0} transactions for ${accountLabel}`;
  }
  showToast(`Loaded ${payload.length || 0} transactions`);
}

function clearTransactionFilters() {
  if (byId("transactionSearch")) byId("transactionSearch").value = "";
  if (byId("transactionFromDate")) byId("transactionFromDate").value = "";
  if (byId("transactionAccountFilter")) byId("transactionAccountFilter").value = "";
  if (byId("transactionToDate")) byId("transactionToDate").value = "";
  const totalEl = byId("transactionsTotal");
  if (totalEl) {
    totalEl.textContent = "Total: 0.00";
  }
  const summaryEl = byId("transactionsSearchSummary");
  if (summaryEl) {
    summaryEl.textContent = "";
  }
}

async function applyTransactionFilters() {
  const accountId = Number(byId("transactionAccountFilter")?.value || 0);
  if (!accountId) {
    throw new Error("Choose an account first");
  }
  await loadTransactions();
}


async function addAsset() {
  const payload = await callApi("/assets", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name: byId("assetName").value.trim(),
      asset_type: byId("assetType").value.trim() || "General",
      purchase_date: byId("assetPurchaseDate").value,
      cost: Number(byId("assetCost").value),
      useful_life_years: Number(byId("assetLifeYears").value || 5),
      salvage_value: Number(byId("assetSalvage").value || 0),
      asset_account_id: Number(byId("assetAccountId").value),
      depreciation_expense_account_id: Number(byId("assetDepExpenseAccountId").value),
    }),
  });
  showToast("Asset added");
  await loadAssets();
  return payload;
}

async function loadAssets() {
  const payload = await callApi("/assets");
  renderAssetsTable(payload);
}

async function addLoan() {
  const payload = await callApi("/loans", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      lender_name: byId("loanLender").value.trim(),
      principal: Number(byId("loanPrincipal").value),
      annual_interest_rate: Number(byId("loanRate").value || 0),
      start_date: byId("loanStartDate").value,
      term_months: Number(byId("loanTermMonths").value),
      liability_account_id: Number(byId("loanLiabilityAccountId").value),
      interest_expense_account_id: Number(byId("loanInterestExpenseAccountId").value),
    }),
  });
  writeOut(out.loans, pretty(payload));
  showToast("Loan added");
  await loadLoans();
}

async function loadLoans() {
  const payload = await callApi("/loans");
  renderLoansTable(payload);
}

async function detectLoanHints() {
  const container = byId("transactionsOut");
  if (container && !container.classList.contains("is-hidden")) {
    container.classList.add("is-hidden");
    return;
  }
  const payload = await callApi("/bank/hints");
  renderLoanHintsTable(payload);
  if (container) container.classList.remove("is-hidden");
}

async function loadLoanSchedule() {
  const loanId = Number(byId("loanScheduleLoanId").value);
  const months = Number(byId("loanScheduleMonths").value || 12);
  if (!loanId) {
    throw new Error("Enter loan ID for schedule");
  }
  const payload = await callApi(`/loans/${loanId}/schedule?months=${months}`);
  const table = renderRowsTable(
    ["Month", "Payment", "Interest", "Principal", "Balance"],
    payload.map((r) => [
      r.month,
      Number(r.payment || 0).toFixed(2),
      Number(r.interest || 0).toFixed(2),
      Number(r.principal || 0).toFixed(2),
      Number(r.balance || 0).toFixed(2),
    ])
  );
  byId("loansOut").innerHTML = table;
}

async function createCustomer() {
  const customer_code = byId("customerCode")?.value?.trim();
  const name = byId("customerName")?.value?.trim();
  const email = byId("customerEmail")?.value?.trim() || "";
  const phone = byId("customerPhone")?.value?.trim() || "";
  if (!customer_code || !name) {
    throw new Error("Customer code and name are required");
  }

  await callApi("/customers", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ customer_code, name, email, phone }),
  });

  byId("customerCode").value = "";
  byId("customerName").value = "";
  byId("customerEmail").value = "";
  byId("customerPhone").value = "";
  showToast("Customer created");
  await loadCustomers();
}

async function loadCustomers() {
  const payload = await callApi("/customers");
  cachedCustomers = Array.isArray(payload) ? payload : [];

  const customerSelect = byId("invoiceCustomerId");
  if (customerSelect) {
    const selected = customerSelect.value || "";
    customerSelect.innerHTML = '<option value="">Customer (optional)</option>';
    cachedCustomers.forEach((c) => {
      const opt = document.createElement("option");
      opt.value = String(c.id);
      opt.textContent = `${c.customer_code} - ${c.name}`;
      customerSelect.appendChild(opt);
    });
    if (selected) customerSelect.value = selected;
  }
}

async function createInventoryItem() {
  const sku = byId("inventorySku")?.value?.trim();
  const name = byId("inventoryName")?.value?.trim();
  const unit_price = Number(byId("inventoryPrice")?.value || 0);
  const quantity_on_hand = Number(byId("inventoryQty")?.value || 0);
  if (!sku || !name) {
    throw new Error("SKU and inventory name are required");
  }

  await callApi("/inventory/items", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sku, name, unit_price, quantity_on_hand }),
  });

  byId("inventorySku").value = "";
  byId("inventoryName").value = "";
  byId("inventoryPrice").value = "";
  byId("inventoryQty").value = "";
  showToast("Inventory item created");
  await loadInventoryItems();
}

async function loadInventoryItems() {
  const payload = await callApi("/inventory/items");
  cachedInventoryItems = Array.isArray(payload) ? payload : [];

  const invSelect = byId("invoiceInventoryItemId");
  if (invSelect) {
    const selected = invSelect.value || "";
    invSelect.innerHTML = '<option value="">Inventory item (optional)</option>';
    cachedInventoryItems.forEach((item) => {
      const opt = document.createElement("option");
      opt.value = String(item.id);
      opt.textContent = `${item.sku} - ${item.name} (QOH ${Number(item.quantity_on_hand || 0).toFixed(2)})`;
      invSelect.appendChild(opt);
    });
    if (selected) invSelect.value = selected;
  }
}

function addInvoiceLineLocal() {
  const description = byId("invoiceLineDescription")?.value?.trim();
  const quantity = Number(byId("invoiceLineQty")?.value || 0);
  const unit_price = Number(byId("invoiceLineUnitPrice")?.value || 0);
  const tax_rate = Number(byId("invoiceLineTaxRate")?.value || 0);
  const income_account_id = Number(byId("invoiceIncomeAccountId")?.value || 0) || null;
  const inventory_item_id = Number(byId("invoiceInventoryItemId")?.value || 0) || null;

  if (!description) {
    throw new Error("Invoice line description is required");
  }
  if (quantity <= 0) {
    throw new Error("Invoice line quantity must be greater than 0");
  }
  if (unit_price < 0) {
    throw new Error("Invoice line unit price must be >= 0");
  }
  if (tax_rate < 0 || tax_rate > 100) {
    throw new Error("Invoice line tax rate must be between 0 and 100");
  }

  draftInvoiceLines.push({ description, quantity, unit_price, tax_rate, income_account_id, inventory_item_id });
  byId("invoiceLineDescription").value = "";
  byId("invoiceLineQty").value = "1";
  byId("invoiceLineUnitPrice").value = "";
  byId("invoiceLineTaxRate").value = "0";
  byId("invoiceIncomeAccountId").value = "";
  byId("invoiceInventoryItemId").value = "";
  renderInvoiceDraftLines();
}

function clearInvoiceLines() {
  draftInvoiceLines = [];
  renderInvoiceDraftLines();
}

async function createInvoice() {
  const invoice_number = byId("invoiceNumber")?.value?.trim() || null;
  const customer_name = byId("invoiceCustomerName")?.value?.trim();
  const customer_email = byId("invoiceCustomerEmail")?.value?.trim() || "";
  const issue_date = byId("invoiceIssueDate")?.value;
  const due_date = byId("invoiceDueDate")?.value;
  const currency = byId("invoiceCurrency")?.value?.trim() || "USD";
  const notes = byId("invoiceNotes")?.value?.trim() || "";
  const customer_id = Number(byId("invoiceCustomerId")?.value || 0) || null;

  if (!customer_name) {
    throw new Error("Customer name is required");
  }
  if (!issue_date || !due_date) {
    throw new Error("Issue date and due date are required");
  }
  if (!draftInvoiceLines.length) {
    throw new Error("Add at least one invoice line");
  }

  const payload = await callApi("/invoices", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      invoice_number,
      customer_id,
      customer_name,
      customer_email,
      issue_date,
      due_date,
      currency,
      notes,
      lines: draftInvoiceLines,
    }),
  });

  byId("invoiceNumber").value = "";
  byId("invoiceCustomerName").value = "";
  byId("invoiceCustomerEmail").value = "";
  byId("invoiceNotes").value = "";
  clearInvoiceLines();
  showToast(`Invoice created: ${payload.invoice_number}`);
  await loadInvoices();
  return payload;
}

async function loadInvoices() {
  const q = byId("invoiceSearch")?.value?.trim() || "";
  const status = byId("invoiceStatusFilter")?.value || "";
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  if (status) params.set("status", status);
  const suffix = params.toString() ? `?${params.toString()}` : "";
  const payload = await callApi(`/invoices${suffix}`);
  renderInvoicesTable(Array.isArray(payload) ? payload : []);
}

async function viewInvoiceDetails(invoiceId) {
  const payload = await callApi(`/invoices/${invoiceId}`);
  const payments = await callApi(`/invoices/${invoiceId}/payments`).catch(() => []);
  const linesTable = renderRowsTable(
    ["Description", "Qty", "Unit", "Tax %", "Line Subtotal", "Tax", "Line Total"],
    (payload.lines || []).map((ln) => [
      ln.description || "",
      Number(ln.quantity || 0).toFixed(2),
      Number(ln.unit_price || 0).toFixed(2),
      Number(ln.tax_rate || 0).toFixed(2),
      Number(ln.line_subtotal || 0).toFixed(2),
      Number(ln.tax_amount || 0).toFixed(2),
      Number(ln.line_total || 0).toFixed(2),
    ])
  );

  out.invoices.innerHTML = `
    <div class="statement-caption">Invoice ${payload.invoice_number} (${payload.status})</div>
    <div class="report-period">
      Customer: ${payload.customer_name} | Issue: ${payload.issue_date} | Due: ${payload.due_date} | Total: ${payload.currency || "USD"} ${Number(payload.total || 0).toFixed(2)} | Outstanding: ${Number(payload.outstanding_balance || 0).toFixed(2)}
    </div>
    <div class="table-actions" style="padding:0.6rem;">
      <button class="btn btn-small" onclick="downloadInvoice(${payload.id})">Download PDF</button>
      <button class="btn btn-small btn-ghost" onclick="sendInvoice(${payload.id})">Mark Sent</button>
      <button class="btn btn-small btn-ghost" onclick="markInvoicePaid(${payload.id})" ${payload.status === "paid" ? "disabled" : ""}>Mark Paid</button>
    </div>
    ${linesTable}
    <div class="statement-caption" style="margin-top:0.7rem;">Payments (${Array.isArray(payments) ? payments.length : 0})</div>
  `;
}

function downloadInvoicePdf(invoiceId) {
  const url = `/invoices/${invoiceId}/download?company_id=${encodeURIComponent(activeCompanyId || 1)}`;
  window.open(url, "_blank");
}

async function markInvoicePaidAction(invoiceId) {
  await callApi(`/invoices/${invoiceId}/mark-paid`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  showToast("Invoice marked paid");
  await loadInvoices();
}

async function sendInvoiceAction(invoiceId) {
  await callApi(`/invoices/${invoiceId}/send`, { method: "POST" });
  showToast("Invoice marked sent");
  await loadInvoices();
}

async function addInvoicePayment() {
  const invoiceId = Number(byId("invoicePaymentInvoiceId")?.value || 0);
  const payment_date = byId("invoicePaymentDate")?.value || new Date().toISOString().slice(0, 10);
  const amount = Number(byId("invoicePaymentAmount")?.value || 0);
  const reference = byId("invoicePaymentReference")?.value?.trim() || "";
  if (!invoiceId) throw new Error("Invoice ID is required for payment");
  if (amount <= 0) throw new Error("Payment amount must be greater than zero");

  await callApi(`/invoices/${invoiceId}/payments`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ payment_date, amount, reference }),
  });

  byId("invoicePaymentAmount").value = "";
  byId("invoicePaymentReference").value = "";
  showToast("Invoice payment recorded");
  await loadInvoices();
}

async function loadArAging() {
  const payload = await callApi("/reports/ar-aging");
  const rows = (payload.by_customer || []).map((r) => [
    r.customer_name,
    Number(r.current || 0).toFixed(2),
    Number(r.days_1_30 || 0).toFixed(2),
    Number(r.days_31_60 || 0).toFixed(2),
    Number(r.days_61_90 || 0).toFixed(2),
    Number(r.days_over_90 || 0).toFixed(2),
    Number(r.total || 0).toFixed(2),
  ]);
  rows.push([
    "TOTAL",
    Number(payload.totals?.current || 0).toFixed(2),
    Number(payload.totals?.days_1_30 || 0).toFixed(2),
    Number(payload.totals?.days_31_60 || 0).toFixed(2),
    Number(payload.totals?.days_61_90 || 0).toFixed(2),
    Number(payload.totals?.days_over_90 || 0).toFixed(2),
    Number(payload.totals?.total || 0).toFixed(2),
  ]);
  out.invoices.innerHTML = `<div class="statement-caption">AR Aging (as of ${payload.as_of})</div>${renderRowsTable(["Customer", "Current", "1-30", "31-60", "61-90", ">90", "Total"], rows)}`;
}

async function createRecurringInvoice() {
  const template_name = byId("recurringName")?.value?.trim();
  const frequency = byId("recurringFrequency")?.value || "monthly";
  const next_run_date = byId("recurringNextRun")?.value;
  const customer_id = Number(byId("invoiceCustomerId")?.value || 0) || null;
  if (!template_name || !next_run_date) {
    throw new Error("Recurring name and next run date are required");
  }
  if (!draftInvoiceLines.length) {
    throw new Error("Add draft invoice lines first to create recurring template");
  }

  await callApi("/recurring-invoices", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ template_name, frequency, next_run_date, customer_id, lines: draftInvoiceLines }),
  });
  showToast("Recurring template created");
}

async function runRecurringInvoicesNow() {
  const payload = await callApi("/recurring-invoices/run", { method: "POST" });
  showToast(`Recurring run created ${payload.created || 0} invoice(s)`);
  await loadInvoices();
}

async function runInvoiceReminders() {
  const payload = await callApi("/invoices/reminders/run", { method: "POST" });
  writeOut(out.invoices, pretty(payload));
  showToast(`Queued reminders: ${payload.queued || 0}`);
}

async function savePeriodLock() {
  const locked_until = byId("periodLockDate")?.value || null;
  const note = byId("periodLockNote")?.value?.trim() || "";
  const payload = await callApi("/period-lock", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ locked_until, note }),
  });
  writeOut(out.invoices, pretty(payload));
  showToast("Period lock saved");
}

async function loadPeriodLock() {
  const payload = await callApi("/period-lock");
  byId("periodLockDate").value = payload.locked_until || "";
  byId("periodLockNote").value = payload.note || "";
  writeOut(out.invoices, pretty(payload));
}

async function addPayrollEmployee() {
  const employee_code = byId("payrollEmployeeCode")?.value?.trim();
  const full_name = byId("payrollEmployeeName")?.value?.trim();
  const photo_url = byId("payrollEmployeePhotoUrl")?.value?.trim() || "";
  const id_number = byId("payrollEmployeeIdNumber")?.value?.trim() || "";
  const tax_number = byId("payrollEmployeeTaxNumber")?.value?.trim() || "";
  const position = byId("payrollEmployeePosition")?.value?.trim() || "";
  const email = byId("payrollEmployeeEmail")?.value?.trim() || "";
  const phone = byId("payrollEmployeePhone")?.value?.trim() || "";
  const hire_date = byId("payrollEmployeeHireDate")?.value || null;
  const bank_account = byId("payrollEmployeeBankAccount")?.value?.trim() || "";
  const nssa_number = byId("payrollEmployeeNssa")?.value?.trim() || "";
  const pension_number = byId("payrollEmployeePension")?.value?.trim() || "";
  const default_gross_salary = Number(byId("payrollEmployeeGross")?.value);
  const tax_rate = Number(byId("payrollEmployeeTaxRate")?.value || 0);

  if (!employee_code || !full_name || Number.isNaN(default_gross_salary)) {
    throw new Error("Provide employee code, name, and gross salary");
  }

  const payload = await callApi("/payroll/employees", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      employee_code,
      full_name,
      photo_url,
      id_number,
      tax_number,
      position,
      email,
      phone,
      hire_date,
      bank_account,
      nssa_number,
      pension_number,
      default_gross_salary,
      tax_rate,
      active: true,
    }),
  });

  byId("payrollEmployeeCode").value = "";
  byId("payrollEmployeeName").value = "";
  byId("payrollEmployeePhotoUrl").value = "";
  byId("payrollEmployeeIdNumber").value = "";
  byId("payrollEmployeeTaxNumber").value = "";
  byId("payrollEmployeePosition").value = "";
  byId("payrollEmployeeEmail").value = "";
  byId("payrollEmployeePhone").value = "";
  byId("payrollEmployeeHireDate").value = "";
  byId("payrollEmployeeBankAccount").value = "";
  byId("payrollEmployeeNssa").value = "";
  byId("payrollEmployeePension").value = "";
  byId("payrollEmployeeGross").value = "";
  byId("payrollEmployeeTaxRate").value = "0";
  showToast("Payroll employee added");
  await loadPayrollEmployees();
  return payload;
}

function renderTaxBrackets() {
  if (!out.taxBrackets) {
    return;
  }
  if (!payrollTaxBrackets.length) {
    writeOut(out.taxBrackets, "No tax brackets loaded.");
    return;
  }

  const lines = payrollTaxBrackets
    .slice()
    .sort((a, b) => Number(a.order_index || 0) - Number(b.order_index || 0))
    .map((b) => {
      const upper = b.upper_limit == null ? "No limit" : Number(b.upper_limit).toFixed(2);
      return `Order ${b.order_index}: ${Number(b.lower_limit || 0).toFixed(2)} to ${upper} @ ${Number(b.rate_percent || 0).toFixed(2)}%`;
    });
  writeOut(out.taxBrackets, lines.join("\n"));
}

async function loadTaxBrackets() {
  const payload = await callApi("/payroll/tax-brackets");
  payrollTaxBrackets = Array.isArray(payload) ? payload : [];
  renderTaxBrackets();
}

function addTaxBracketLocal() {
  const lower = Number(byId("taxBracketLower")?.value);
  const upperRaw = byId("taxBracketUpper")?.value;
  const upper = upperRaw === "" ? null : Number(upperRaw);
  const rate = Number(byId("taxBracketRate")?.value);
  const order = Number(byId("taxBracketOrder")?.value || 1);

  if (Number.isNaN(lower) || Number.isNaN(rate) || Number.isNaN(order)) {
    throw new Error("Provide valid bracket lower, rate, and order");
  }
  if (upper !== null && Number.isNaN(upper)) {
    throw new Error("Upper limit must be number or blank");
  }

  payrollTaxBrackets.push({
    lower_limit: lower,
    upper_limit: upper,
    rate_percent: rate,
    order_index: order,
  });
  renderTaxBrackets();

  byId("taxBracketLower").value = "";
  byId("taxBracketUpper").value = "";
  byId("taxBracketRate").value = "";
  byId("taxBracketOrder").value = String(order + 1);
}

async function saveTaxBrackets() {
  if (!payrollTaxBrackets.length) {
    throw new Error("Add or load at least one tax bracket first");
  }
  const payload = await callApi("/payroll/tax-brackets", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ brackets: payrollTaxBrackets.map((b) => ({
      lower_limit: Number(b.lower_limit || 0),
      upper_limit: b.upper_limit === null || b.upper_limit === "" ? null : Number(b.upper_limit),
      rate_percent: Number(b.rate_percent || 0),
      order_index: Number(b.order_index || 1),
    })) }),
  });
  payrollTaxBrackets = Array.isArray(payload) ? payload : [];
  renderTaxBrackets();
  showToast("Tax brackets saved");
}

async function loadPayrollEmployees(searchText = "") {
  const query = searchText && searchText.trim() ? `?q=${encodeURIComponent(searchText.trim())}` : "";
  const payload = await callApi(`/payroll/employees${query}`);
  renderPayrollEmployeesTable(payload);
}

async function searchPayrollEmployees() {
  const q = byId("payrollEmployeeSearch")?.value || "";
  await loadPayrollEmployees(q);
}

async function viewPayrollEmployeeDetails(employeeId) {
  const payload = await callApi(`/payroll/employees/${employeeId}`);
  byId("payrollDocEmployeeId").value = String(employeeId);
  renderPayrollEmployeeDetail(payload);
  renderPayrollDocumentVault(payload.documents || []);
}

async function uploadPayrollEmployeeDocument() {
  const employeeId = Number(byId("payrollDocEmployeeId")?.value || 0);
  const fileInput = byId("payrollDocFile");
  const file = fileInput?.files?.[0];
  const docType = byId("payrollDocType")?.value || "other";
  const title = byId("payrollDocTitle")?.value?.trim() || "";

  if (!employeeId) {
    throw new Error("Enter employee ID for document upload");
  }
  if (!file) {
    throw new Error("Choose a file to upload");
  }

  const form = new FormData();
  form.append("doc_type", docType);
  form.append("title", title);
  form.append("file", file);

  await callApi(`/payroll/employees/${employeeId}/documents`, {
    method: "POST",
    body: form,
  });

  byId("payrollDocTitle").value = "";
  byId("payrollDocFile").value = "";
  showToast("Employee document uploaded");
  await loadPayrollDocVault();
}

async function loadPayrollDocVault() {
  const employeeId = Number(byId("payrollDocEmployeeId")?.value || 0);
  if (!employeeId) {
    throw new Error("Enter employee ID to load document vault");
  }
  const payload = await callApi(`/payroll/employees/${employeeId}/documents`);
  renderPayrollDocumentVault(Array.isArray(payload) ? payload : []);
  return payload;
}

function downloadPayrollDocument(docId) {
  const url = `/payroll/documents/${docId}/download?company_id=${encodeURIComponent(activeCompanyId || 1)}`;
  window.open(url, "_blank");
}

function wirePayrollDocDropZone() {
  const zone = byId("payrollDocDropZone");
  const fileInput = byId("payrollDocFile");
  if (!zone || !fileInput) {
    return;
  }

  ["dragenter", "dragover"].forEach((eventName) => {
    zone.addEventListener(eventName, (event) => {
      event.preventDefault();
      zone.classList.add("active");
    });
  });

  ["dragleave", "drop"].forEach((eventName) => {
    zone.addEventListener(eventName, (event) => {
      event.preventDefault();
      zone.classList.remove("active");
    });
  });

  zone.addEventListener("drop", (event) => {
    const files = event.dataTransfer?.files;
    if (!files || !files.length) {
      return;
    }
    fileInput.files = files;
    showToast(`Selected file: ${files[0].name}`);
  });
}

async function createPayrollRun() {
  const period_label = byId("payrollPeriodLabel")?.value?.trim();
  const pay_date = byId("payrollPayDate")?.value;
  const expense_account_id = Number(byId("payrollExpenseAccountId")?.value || 0);
  const payable_account_id = Number(byId("payrollPayableAccountId")?.value || 0);
  const rawTaxId = Number(byId("payrollTaxLiabilityAccountId")?.value || 0);
  const tax_liability_account_id = rawTaxId > 0 ? rawTaxId : null;
  const paye_rate_raw = byId("payrollPayeRate")?.value;
  const paye_rate = paye_rate_raw === "" || paye_rate_raw == null ? null : Number(paye_rate_raw);
  const nssa_rate = Number(byId("payrollNssaRate")?.value || 0);
  const pension_rate = Number(byId("payrollPensionRate")?.value || 0);
  const sdl_rate = Number(byId("payrollSdlRate")?.value || 0);
  const other_deduction_per_employee = Number(byId("payrollOtherDeduction")?.value || 0);

  if (!period_label || !pay_date || !expense_account_id || !payable_account_id) {
    throw new Error("Provide period, pay date, expense account, and payable account");
  }

  const payload = await callApi("/payroll/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      period_label,
      pay_date,
      expense_account_id,
      payable_account_id,
      tax_liability_account_id,
      paye_rate,
      nssa_rate,
      pension_rate,
      sdl_rate,
      other_deduction_per_employee,
    }),
  });

  showToast("Payroll run generated");
  await loadPayrollRuns();
  return payload;
}

async function loadPayrollRuns() {
  const payload = await callApi("/payroll/runs");
  renderPayrollRunsTable(payload);
}

async function viewPayrollRunDetails(runId) {
  const payload = await callApi(`/payroll/runs/${runId}`);
  const bodyRows = (payload.lines || [])
    .map(
      (ln) => `
      <tr>
        <td>${ln.employee_code || ""}</td>
        <td>${ln.employee_name || ""}</td>
        <td>${Number(ln.gross_pay || 0).toFixed(2)}</td>
        <td>${Number(ln.tax_amount || 0).toFixed(2)}</td>
        <td>${Number(ln.nssa_amount || 0).toFixed(2)}</td>
        <td>${Number(ln.pension_amount || 0).toFixed(2)}</td>
        <td>${Number(ln.other_deduction || 0).toFixed(2)}</td>
        <td>${Number(ln.sdl_amount || 0).toFixed(2)}</td>
        <td>${Number(ln.net_pay || 0).toFixed(2)}</td>
        <td>
          <div class="table-actions">
            <button class="btn btn-small btn-ghost" onclick="downloadPayslip(${payload.id}, ${ln.employee_id})">Payslip</button>
            <button class="btn btn-small btn-ghost" onclick="downloadTaxCertificate(${payload.id}, ${ln.employee_id})">Tax Cert</button>
          </div>
        </td>
      </tr>
    `
    )
    .join("");

  byId("payrollOut").innerHTML = `
    <div class="statement-caption">Payroll Run #${payload.id} - ${payload.period_label}</div>
    <div class="report-period">
      Pay Date: ${payload.pay_date} | Status: ${payload.status} |
      Gross: ${Number(payload.total_gross || 0).toFixed(2)} |
      PAYE: ${Number(payload.total_tax || 0).toFixed(2)} |
      NSSA: ${Number(payload.total_nssa || 0).toFixed(2)} |
      Pension: ${Number(payload.total_pension || 0).toFixed(2)} |
      SDL: ${Number(payload.total_sdl || 0).toFixed(2)} |
      Net: ${Number(payload.total_net || 0).toFixed(2)}
    </div>
    <table class="friendly-table">
      <thead>
        <tr>
          <th>Code</th><th>Employee</th><th>Gross</th><th>PAYE</th><th>NSSA</th><th>Pension</th><th>Other</th><th>SDL</th><th>Net</th><th>Documents</th>
        </tr>
      </thead>
      <tbody>${bodyRows}</tbody>
    </table>
  `;
}

async function postPayrollRunAction(runId) {
  const payload = await callApi(`/payroll/runs/${runId}/post`, {
    method: "POST",
  });
  showToast(`Payroll ${payload.status}`);
  await loadPayrollRuns();
}

async function payPayrollRunAction(runId) {
  const bank_account_id = Number(byId("payrollBankAccountId")?.value || 0);
  const payment_date = byId("payrollPayDate")?.value || new Date().toISOString().slice(0, 10);
  if (!bank_account_id) {
    throw new Error("Select payroll payment bank account first");
  }

  const payload = await callApi(`/payroll/runs/${runId}/pay`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ bank_account_id, payment_date }),
  });
  showToast(`Payroll ${payload.status}`);
  await loadPayrollRuns();
}

function downloadPayrollRunSummary(runId, format = "pdf") {
  const url = `/payroll/runs/${runId}/download?format=${encodeURIComponent(format)}&company_id=${encodeURIComponent(activeCompanyId || 1)}`;
  window.open(url, "_blank");
}

function downloadPayrollPayslip(runId, employeeId) {
  const url = `/payroll/runs/${runId}/payslip/${employeeId}?company_id=${encodeURIComponent(activeCompanyId || 1)}`;
  window.open(url, "_blank");
}

function downloadPayrollTaxCertificate(runId, employeeId) {
  const url = `/payroll/runs/${runId}/tax-certificate/${employeeId}?company_id=${encodeURIComponent(activeCompanyId || 1)}`;
  window.open(url, "_blank");
}

function downloadEmploymentCert(employeeId) {
  const url = `/payroll/employees/${employeeId}/employment-certificate?company_id=${encodeURIComponent(activeCompanyId || 1)}`;
  window.open(url, "_blank");
}

async function allocate() {
  const payload = await callApi("/bookkeeping/allocate", { method: "POST" });
  writeOut(out.process, pretty(payload));
}

async function postJournals() {
  const payload = await callApi("/bookkeeping/post", { method: "POST" });
  writeOut(out.process, pretty(payload));
}

async function fullRun() {
  const allocateResult = await callApi("/bookkeeping/allocate", { method: "POST" });
  const postResult = await callApi("/bookkeeping/post", { method: "POST" });
  writeOut(out.process, pretty({ allocate: allocateResult, post: postResult }));
  showToast("Bookkeeping run complete");
  await loadTransactions();
}

async function loadUnmatched() {
  const card = document.getElementById("unmatchedCard");
  const container = document.getElementById("unmatchedOut");
  if (container && !container.classList.contains("is-hidden")) {
    container.classList.add("is-hidden");
    if (card) card.classList.remove("active");
    return;
  }
  const payload = await callApi("/bookkeeping/documents");
  renderUnmatchedTable(payload.unmatched_transactions || []);
  if (container) container.classList.remove("is-hidden");
  if (card) card.classList.add("active");
}

async function loadHints() {
  const container = byId("transactionsOut");
  if (container && !container.classList.contains("is-hidden")) {
    container.classList.add("is-hidden");
    return;
  }
  const payload = await callApi("/bank/hints");
  if (Array.isArray(payload) && payload.length) {
    renderLoanHintsTable(payload);
  } else {
    if (container) container.innerHTML = '<div class="empty-table">No loan/tax/interest hints found in imported transactions.</div>';
  }
  if (container) container.classList.remove("is-hidden");
}

async function detectLoanHints() {
  const container = byId("transactionsOut");
  if (container && !container.classList.contains("is-hidden")) {
    container.classList.add("is-hidden");
    return;
  }
  const payload = await callApi("/bank/hints");
  renderLoanHintsTable(payload);
  if (container) container.classList.remove("is-hidden");
}

async function loadReport() {
  const map = {
    trial: "/reports/trial-balance",
    pnl: "/reports/profit-loss",
    bs: "/reports/balance-sheet",
    cf: "/reports/cash-flow",
    cfp: "/reports/cash-flow-projection",
    gl: "/reports/general-ledger",
  };
  const period = getReportPeriod();
  const projection = getProjectionAssumptions();
  const params = new URLSearchParams();
  if (period.from) {
    params.set("from_date", period.from);
  }
  if (period.to) {
    params.set("to_date", period.to);
  }
  if (activeReport === "cfp") {
    params.set("months", String(projection.months));
    params.set("inflow_growth_pct", String(projection.inflowGrowth));
    params.set("outflow_growth_pct", String(projection.outflowGrowth));
    if (projection.openingOverride !== null && !Number.isNaN(projection.openingOverride)) {
      params.set("opening_balance_override", String(projection.openingOverride));
    }
  }
  const query = params.toString();
  const endpoint = query ? `${map[activeReport]}?${query}` : map[activeReport];
  const payload = await callApi(endpoint);
  renderReportView(activeReport, payload);
}

async function loadAllStatements() {
  const payload = await callApi("/reports/all");
  writeOut(out.statements, pretty(payload));
}

async function saveCompanyProfile() {
  const payload = await callApi("/company/profile", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      company_name: byId("companyName").value.trim(),
      address: byId("companyAddress").value.trim(),
      email: byId("companyEmail").value.trim(),
      phone: byId("companyPhone").value.trim(),
      tax_number: byId("companyTaxNumber").value.trim(),
      currency: byId("companyCurrency").value.trim() || "USD",
    }),
  });
  writeOut(out.statements, pretty(payload));
  showToast("Company profile saved");
}

async function loadCompanyProfile() {
  const payload = await callApi("/company/profile");
  byId("companyName").value = payload.company_name || "";
  byId("companyAddress").value = payload.address || "";
  byId("companyEmail").value = payload.email || "";
  byId("companyPhone").value = payload.phone || "";
  byId("companyTaxNumber").value = payload.tax_number || "";
  byId("companyCurrency").value = payload.currency || "USD";
  writeOut(out.statements, pretty(payload));
}

function downloadStatement() {
  const reportName = byId("downloadReportName").value;
  const format = byId("downloadFormat").value;
  const comparative = byId("downloadComparative")?.checked !== false;
  const period = getReportPeriod();
  const projection = getProjectionAssumptions();
  const params = new URLSearchParams();
  params.set("format", format);
  params.set("period_label", period.label);
  params.set("compare", comparative ? "true" : "false");
  if (period.from) {
    params.set("from_date", period.from);
  }
  if (period.to) {
    params.set("to_date", period.to);
  }
  if (reportName === "cash-flow-projection") {
    params.set("months", String(projection.months));
    params.set("inflow_growth_pct", String(projection.inflowGrowth));
    params.set("outflow_growth_pct", String(projection.outflowGrowth));
    if (projection.openingOverride !== null && !Number.isNaN(projection.openingOverride)) {
      params.set("opening_balance_override", String(projection.openingOverride));
    }
  }
  const url = `/reports/download/${reportName}?${params.toString()}`;
  window.open(url, "_blank");
}

function downloadFilteredTransactions() {
  const accountId = Number(byId("transactionAccountFilter")?.value || 0);
  if (!accountId) {
    throw new Error("Choose an account first");
  }
  const query = buildTransactionFilterQuery();
  const path = query ? `/bank/transactions/download?${query}` : "/bank/transactions/download";
  const url = buildApiUrl(path);
  url.searchParams.set("company_id", String(activeCompanyId || 1));
  url.searchParams.set("format", "csv");
  window.open(url.toString(), "_blank");
}

function wireTabs() {
  document.querySelectorAll(".tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((x) => x.classList.remove("active"));
      btn.classList.add("active");
      activeReport = btn.dataset.report;
    });
  });
}

function bind(id, fn, output) {
  const element = byId(id);
  if (!element) {
    console.warn(`Missing UI element: ${id}`);
    return;
  }

  element.addEventListener("click", async () => {
    const originalLabel = element.textContent;
    element.disabled = true;
    element.classList.add("is-busy");
    if (output) {
      writeOut(output, `Running '${originalLabel}'...`);
    }
    try {
      await fn();
    } catch (err) {
      writeOut(output, `Error: ${err.message || err}`);
      console.error(`Action failed for ${id}:`, err);
      showToast(err.message);
    } finally {
      element.disabled = false;
      element.classList.remove("is-busy");
    }
  });
}

bind("seedAllBtn", seedAllData, out.process);
bind("createCompanyBtn", createCompany, out.process);
bind("deleteCompanyBtn", deleteCompany, out.process);
bind("setOpeningBalanceBtn", setOpeningBalance, out.import);
bind("loadBalanceSummaryBtn", loadBalanceSummary, out.import);
bind("loadRunningBalanceBtn", toggleRunningBalance, out.import);
bind("importBtn", importBank, out.import);
bind("addRuleBtn", addRule, out.rules);
bind("deleteRuleBtn", deleteRule, out.rules);
bind("loadAccountsBtn", loadAccounts, out.rules);
bind("refreshRulesBtn", loadRules, out.rules);
bind("addAccountBtn", createAccount, out.accounts);
bind("deleteAccountBtn", deleteAccount, out.accounts);
bind("refreshAccountsBtn", loadAndShowAccounts, out.accounts);
bind("toggleAccountsTableBtn", toggleAccountsTable, out.accounts);
bind("allocateBtn", allocate, out.process);
bind("postBtn", postJournals, out.process);
bind("fullRunBtn", fullRun, out.process);
bind("loadUnmatchedBtn", loadUnmatched, out.unmatched);
bind("loadTransactionsBtn", loadTransactions, out.transactions);
bind("loadHintsBtn", loadHints, out.transactions);
bind("filterTransactionsBtn", applyTransactionFilters, out.transactions);
bind("clearTransactionFiltersBtn", async () => {
  clearTransactionFilters();
  await loadTransactions();
}, out.transactions);
bind("downloadFilteredTransactionsBtn", downloadFilteredTransactions, out.transactions);
bind("addTransactionBtn", addManualTransaction, out.transactions);
bind("updateTransactionBtn", updateManualTransaction, out.transactions);
bind("clearTransactionFormBtn", clearTransactionForm, out.transactions);
bind("createCustomerBtn", createCustomer, out.invoices);
bind("loadCustomersBtn", loadCustomers, out.invoices);
bind("createInventoryBtn", createInventoryItem, out.invoices);
bind("loadInventoryBtn", loadInventoryItems, out.invoices);
bind("addInvoiceLineBtn", addInvoiceLineLocal, out.invoiceDraft);
bind("clearInvoiceLinesBtn", clearInvoiceLines, out.invoiceDraft);
bind("createInvoiceBtn", createInvoice, out.invoices);
bind("loadInvoicesBtn", loadInvoices, out.invoices);
bind("searchInvoicesBtn", loadInvoices, out.invoices);
bind("addInvoicePaymentBtn", addInvoicePayment, out.invoices);
bind("loadArAgingBtn", loadArAging, out.invoices);
bind("createRecurringBtn", createRecurringInvoice, out.invoices);
bind("runRecurringBtn", runRecurringInvoicesNow, out.invoices);
bind("runInvoiceRemindersBtn", runInvoiceReminders, out.invoices);
bind("savePeriodLockBtn", savePeriodLock, out.invoices);
bind("loadPeriodLockBtn", loadPeriodLock, out.invoices);
bind("addAssetBtn", addAsset, out.assets);
bind("loadAssetsBtn", loadAssets, out.assets);
bind("addLoanBtn", addLoan, out.loans);
bind("loadLoansBtn", loadLoans, out.loans);
bind("detectLoanHintsBtn", detectLoanHints, out.loans);
bind("loadLoanScheduleBtn", loadLoanSchedule, out.loans);
bind("addPayrollEmployeeBtn", addPayrollEmployee, out.payroll);
bind("loadPayrollEmployeesBtn", loadPayrollEmployees, out.payroll);
bind("searchPayrollEmployeeBtn", searchPayrollEmployees, out.payroll);
bind("uploadPayrollDocBtn", uploadPayrollEmployeeDocument, out.payrollDocVault);
bind("loadPayrollDocVaultBtn", loadPayrollDocVault, out.payrollDocVault);
bind("createPayrollRunBtn", createPayrollRun, out.payroll);
bind("loadPayrollRunsBtn", loadPayrollRuns, out.payroll);
bind("addTaxBracketBtn", addTaxBracketLocal, out.taxBrackets);
bind("saveTaxBracketsBtn", saveTaxBrackets, out.taxBrackets);
bind("loadTaxBracketsBtn", loadTaxBrackets, out.taxBrackets);
bind("refreshReportsBtn", loadReport, out.reports);
bind("loadAllStatementsBtn", loadAllStatements, out.statements);
bind("downloadStatementBtn", downloadStatement, out.statements);
bind("saveCompanyProfileBtn", saveCompanyProfile, out.statements);
bind("loadCompanyProfileBtn", loadCompanyProfile, out.statements);
wireTabs();
wirePayrollDocDropZone();
loadCompanies().catch((err) => {
  writeOut(out.process, `Error: ${err.message || err}`);
});
renderInvoiceDraftLines();
const invoiceCustomerSelect = byId("invoiceCustomerId");
if (invoiceCustomerSelect) {
  invoiceCustomerSelect.addEventListener("change", () => {
    const id = Number(invoiceCustomerSelect.value || 0);
    const customer = cachedCustomers.find((x) => Number(x.id) === id);
    if (!customer) return;
    byId("invoiceCustomerName").value = customer.name || "";
    byId("invoiceCustomerEmail").value = customer.email || "";
  });
}
const activeCompanyEl = byId("activeCompanyId");
if (activeCompanyEl) {
  activeCompanyEl.addEventListener("change", async () => {
    activeCompanyId = Number(activeCompanyEl.value || 1);
    localStorage.setItem("activeCompanyId", String(activeCompanyId));
    showToast(`Switched to company ${activeCompanyId}`);
    await refreshCompanyContext();
  });
}
loadAccounts().catch(() => {});
loadTaxBrackets().catch(() => {});
setAccountsTableVisibility(false);
loadCompanyProfile().catch(() => {});
window.manualAllocate = (...args) => {
  manualAllocateTxn(...args).catch((err) => {
    writeOut(out.unmatched, `Error: ${err.message || err}`);
    showToast(err.message || "Manual allocation failed");
  });
};
window.openCreateAccountForm = openCreateAccountForm;
window.appendRuleKeyword = (...args) => {
  appendRuleKeywordToRule(...args).catch((err) => {
    writeOut(out.process, `Error: ${err.message || err}`);
    showToast(err.message || "Keyword update failed");
  });
};
window.reassignTransaction = (...args) => {
  reassignTransactionAccount(...args).catch((err) => {
    writeOut(out.transactions, `Error: ${err.message || err}`);
    showToast(err.message || "Transaction update failed");
  });
};
window.editTransaction = (...args) => {
  editTransactionById(...args).catch((err) => {
    writeOut(out.transactions, `Error: ${err.message || err}`);
    showToast(err.message || "Transaction edit failed");
  });
};
window.deleteTransaction = (...args) => {
  deleteTransactionById(...args).catch((err) => {
    writeOut(out.transactions, `Error: ${err.message || err}`);
    showToast(err.message || "Transaction delete failed");
  });
};
window.postPayrollRun = (...args) => {
  postPayrollRunAction(...args).catch((err) => {
    writeOut(out.payroll, `Error: ${err.message || err}`);
    showToast(err.message || "Payroll posting failed");
  });
};
window.payPayrollRun = (...args) => {
  payPayrollRunAction(...args).catch((err) => {
    writeOut(out.payroll, `Error: ${err.message || err}`);
    showToast(err.message || "Payroll payment failed");
  });
};
window.downloadPayrollRun = (...args) => {
  downloadPayrollRunSummary(...args);
};
window.downloadPayslip = (...args) => {
  downloadPayrollPayslip(...args);
};
window.downloadTaxCertificate = (...args) => {
  downloadPayrollTaxCertificate(...args);
};
window.downloadEmploymentCertificate = (...args) => {
  downloadEmploymentCert(...args);
};
window.downloadPayrollDocument = (...args) => {
  downloadPayrollDocument(...args);
};
window.viewInvoice = (...args) => {
  viewInvoiceDetails(...args).catch((err) => {
    writeOut(out.invoices, `Error: ${err.message || err}`);
    showToast(err.message || "Invoice lookup failed");
  });
};
window.markInvoicePaid = (...args) => {
  markInvoicePaidAction(...args).catch((err) => {
    writeOut(out.invoices, `Error: ${err.message || err}`);
    showToast(err.message || "Mark paid failed");
  });
};
window.sendInvoice = (...args) => {
  sendInvoiceAction(...args).catch((err) => {
    writeOut(out.invoices, `Error: ${err.message || err}`);
    showToast(err.message || "Send invoice failed");
  });
};
window.downloadInvoice = (...args) => {
  downloadInvoicePdf(...args);
};
window.viewPayrollRun = (...args) => {
  viewPayrollRunDetails(...args).catch((err) => {
    writeOut(out.payroll, `Error: ${err.message || err}`);
    showToast(err.message || "Payroll run lookup failed");
  });
};
window.viewPayrollEmployee = (...args) => {
  viewPayrollEmployeeDetails(...args).catch((err) => {
    writeOut(out.payrollEmployeeDetail, `Error: ${err.message || err}`);
    showToast(err.message || "Employee profile lookup failed");
  });
};
