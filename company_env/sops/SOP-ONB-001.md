---
id: SOP-ONB-001
title: Onboard a new employee
triggers: [onboard, onboarding, new, hire, joiner, joining, employee, welcome]
---
# SOP-ONB-001 - Onboard a new employee

**Systems:** hr_portal (employee record, accounts), ticketing (laptop), files (welcome letter), email (external).

1. **Check for an existing record** (`hr` db, by email). If one exists, stop and ask the human.
2. **Create the employee record** in the HR portal (*New employee*): name, email, department, cost center, manager, start date.
   Take the cost center from the manager's record unless the request gives one. Record the new `emp_code` shown on the employee page with `memory.set`.
3. **Create accounts** from the employee page: `email`, `vpn` and `slack` (one *Add account* per system). Engineers also get `github`.
4. **Open a laptop ticket** in ticketing: title "Laptop for <name>", category Hardware, requester = manager's name, details with start date and department.
5. **Generate the welcome letter** with `files.write_docx` from template `company_env/data/templates/welcome_template.docx`
   into `company_env/data/out/welcome_<First>_<Last>.docx`, filling fields name, start_date, department, manager, emp_code.
6. **Ask before emailing.** Sending the welcome email to the new hire's personal address is an external action and always requires human approval
   (use `email.send` only after approval; the policy gate will ask).
