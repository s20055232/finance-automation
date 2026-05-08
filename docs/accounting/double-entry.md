# Double-Entry Bookkeeping

Every financial transaction is recorded **twice** — once as a debit and once as a credit.
This is the foundation of modern accounting, dating back to 15th-century Italy.

## The Golden Rule

```
Total Debits = Total Credits = 0
```

Think of it like a scale: every time money moves, both sides must balance.

---

## Interactive Tutorial

The following interactive tool walks through double-entry concepts with real examples.
Try entering a transaction to see how debit and credit entries are generated automatically.

<div style="border: 1px solid #e0e0e0; border-radius: 8px; overflow: hidden; margin: 1.5rem 0;">
  <iframe
    src="https://claude.site/artifacts/ef3eb6a1-9858-46c4-b71b-1a43dadca397"
    title="Accounting Basics — Interactive Tutorial"
    width="100%"
    height="620"
    frameborder="0"
    allow="clipboard-write"
    allowfullscreen>
  </iframe>
</div>

---

## How This Bot Applies Double-Entry

When the AI classifies an invoice as **equipment**, it automatically generates:

```
Debit:  Equipment          $4,097.98   ← asset increases (we now own a laptop)
Credit: Cash               $4,097.98   ← asset decreases (we paid cash)
```

When classified as **professional services**:

```
Debit:  Professional Services  $1,270.00  ← expense incurred
Credit: Accounts Payable       $1,270.00  ← liability (not yet paid)
```

The system validates every invoice: if `sum(debits) ≠ sum(credits)`, it flags the entry as a **CRITICAL anomaly** and triggers an email alert.

---

## Five Account Types

| Type | Normal Balance | Increases with | Examples |
|------|---------------|---------------|---------|
| **Asset** | Debit | Debit | Cash, Equipment, Receivables |
| **Liability** | Credit | Credit | Accounts Payable, Loans |
| **Equity** | Credit | Credit | Common Stock, Retained Earnings |
| **Revenue** | Credit | Credit | Sales Revenue, Service Fees |
| **Expense** | Debit | Debit | Rent, Salaries, Marketing |

!!! tip "Memory trick"
    **DEALER** — **D**ividends, **E**xpenses, **A**ssets increase with **D**ebits;
    **L**iabilities, **E**quity, **R**evenue increase with **C**redits.
