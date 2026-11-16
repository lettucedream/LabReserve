import { PASSWORD_HINT, passwordError } from "./password-policy.mjs";

const $ = selector => document.querySelector(selector);

export function mountAuth(onChange) {
  let session = null, users = [];
  function setSession(value) {
    const hadSession = Boolean(session?.user);
    session = value;
    const loggedIn = Boolean(session?.user);
    $("#auth-view").hidden = loggedIn;
    $("#app-content").hidden = !loggedIn;
    $("#main-nav").hidden = !loggedIn;
    $("#account-actions").hidden = !loggedIn;
    $("#manage-open").hidden = session?.user.role !== "admin";
    if (!loggedIn) {
      users = [];
      for (const dialog of document.querySelectorAll("dialog[open]")) dialog.close();
      $("#recovery-code").value = "";
      showAuth("login");
      if (hadSession) for (const form of document.querySelectorAll("[data-auth-form]")) form.reset();
      for (const id of ["admin-create-form", "admin-reset-form", "admin-delete-form"]) $("#" + id).reset();
      $("#admin-users").replaceChildren();
      document.title = "Accedi · LabReserve";
    }
    onChange(session);
  }
  async function request(path, { method = "GET", body } = {}) {
    const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 12000);
    try {
      const headers = { Accept: "application/json" };
      if (body !== undefined) headers["Content-Type"] = "application/json";
      if (session?.csrf_token && method !== "GET") headers["X-CSRF-Token"] = session.csrf_token;
      const response = await fetch(`/api/availability/auth${path}`, { method, headers, credentials: "same-origin", body: body === undefined ? undefined : JSON.stringify(body), signal: controller.signal, cache: "no-store" });
      const result = response.status === 204 ? null : await response.json();
      if (!response.ok) {
        if (response.status === 401 && session) setSession(null);
        throw new Error(typeof result?.detail === "string" ? result.detail : "Controlla i campi inseriti. " + PASSWORD_HINT);
      }
      return result;
    } catch (error) {
      if (error.name === "AbortError" || error instanceof TypeError) throw new Error("Connessione non riuscita. Riprova tra poco.");
      throw error;
    } finally { clearTimeout(timeout); }
  }
  function showCode(code) {
    $("#recovery-code").value = code;
    $("#recovery-dialog").showModal();
  }
  function showAuth(view) {
    for (const form of document.querySelectorAll("[data-auth-form]")) form.hidden = form.dataset.authForm !== view;
    for (const button of document.querySelectorAll("[data-auth-view]")) button.setAttribute("aria-pressed", String(button.dataset.authView === view));
    $("#auth-title").textContent = { login: "Accedi a LabReserve", register: "Crea un account", recover: "Recupera il tuo account" }[view];
  }
  async function submit(form, work) {
    const button = form.querySelector('[type="submit"]'), result = form.querySelector(".form-result");
    if (button.disabled) return;
    button.disabled = true; result.textContent = ""; result.classList.remove("error");
    try {
      const fields = Object.fromEntries(new FormData(form));
      const password = fields.new_password ?? fields.password;
      if (password && form.querySelector('[autocomplete="new-password"]') && passwordError(password)) throw new Error(passwordError(password));
      if ("confirmation" in fields && fields.confirmation !== password) throw new Error("Le password non coincidono.");
      delete fields.confirmation;
      await work(fields, result);
    } catch (error) { result.textContent = error.message; result.classList.add("error"); }
    finally { button.disabled = false; }
  }
  for (const input of document.querySelectorAll('input[autocomplete="new-password"]:not([name="confirmation"])')) {
    input.setAttribute("aria-describedby", input.form.id + "-password-hint");
    input.addEventListener("input", () => input.setCustomValidity(input.value ? passwordError(input.value) : ""));
    input.form.addEventListener("reset", () => input.setCustomValidity(""));
  }
  for (const button of document.querySelectorAll("[data-auth-view]")) button.addEventListener("click", () => showAuth(button.dataset.authView));
  for (const kind of ["login", "register"]) $("#" + kind + "-form").addEventListener("submit", event => {
    event.preventDefault();
    submit(event.currentTarget, async fields => {
      const result = await request("/" + kind, { method: "POST", body: fields });
      setSession(result); event.target.reset();
      if (result.recovery_code) showCode(result.recovery_code);
    });
  });
  $("#recover-form").addEventListener("submit", event => {
    event.preventDefault();
    submit(event.currentTarget, async fields => {
      fields.new_username ||= null;
      const result = await request("/recover", { method: "POST", body: fields });
      event.target.reset(); showAuth("login");
      $("#login-form").elements.username.value = result.username;
      $("#login-form").elements.password.value = "";
      $("#login-form .form-result").textContent = result.message;
      showCode(result.recovery_code);
    });
  });
  $("#user-open").addEventListener("click", () => {
    $("#account-form").reset(); $("#account-form").elements.new_username.value = session.user.username;
    $("#account-form .form-result").textContent = ""; $("#account-dialog").showModal();
  });
  $("#account-form").addEventListener("submit", event => {
    event.preventDefault();
    submit(event.currentTarget, async (fields, result) => {
      fields.new_password ||= null;
      const next = await request("/account", { method: "PATCH", body: fields });
      setSession(next); event.target.reset(); event.target.elements.new_username.value = next.user.username;
      result.textContent = "Account aggiornato. Le altre sessioni sono state disconnesse.";
    });
  });
  $("#recovery-new").addEventListener("click", async event => {
    const form = $("#account-form"), result = form.querySelector(".form-result");
    if (!form.elements.current_password.reportValidity()) return;
    event.target.disabled = true;
    try {
      const response = await request("/recovery-code", { method: "POST", body: { current_password: form.elements.current_password.value } });
      form.elements.current_password.value = ""; showCode(response.recovery_code);
    } catch (error) { result.textContent = error.message; result.classList.add("error"); }
    finally { event.target.disabled = false; }
  });
  $("#logout").addEventListener("click", async event => {
    event.target.disabled = true;
    try { await request("/logout", { method: "POST" }); setSession(null); }
    catch (error) { $("#account-form .form-result").textContent = error.message; }
    finally { event.target.disabled = false; }
  });
  $("#recovery-saved").addEventListener("click", () => { $("#recovery-dialog").close(); $("#recovery-code").value = ""; });
  $("#recovery-dialog").addEventListener("close", () => { $("#recovery-code").value = ""; });
  $("#account-dialog").addEventListener("close", () => $("#account-form").reset());
  $("#recovery-code").addEventListener("focus", event => event.target.select());
  function selectAdminUser() {
    const user = users.find(user => user.id === $("#admin-users").value);
    const form = $("#admin-reset-form");
    form.elements.new_username.value = user?.username || "";
    form.elements.new_password.value = form.elements.admin_password.value = "";
    form.elements.new_password.setCustomValidity("");
    form.querySelector('[type="submit"]').disabled = !user;
    $("#admin-delete-open").disabled = !user;
    form.querySelector(".form-result").textContent = "";
  }
  async function loadUsers(selected = $("#admin-users").value) {
    const select = $("#admin-users"), result = $("#admin-reset-form .form-result");
    const accountId = session?.user.id;
    try {
      const response = await request("/users");
      if (session?.user.role !== "admin" || session.user.id !== accountId) return;
      users = response.filter(user => user.role !== "admin");
      select.replaceChildren(...users.map(user => new Option(user.username + (user.initialized ? "" : " (da attivare)"), user.id)));
      if (!users.length) select.add(new Option("Nessun utente registrato", ""));
      if (users.some(user => user.id === selected)) select.value = selected;
      selectAdminUser(); result.textContent = "";
    } catch (error) {
      if (session?.user.id === accountId) { result.textContent = error.message; result.classList.add("error"); }
    }
  }
  $("#admin-users").addEventListener("change", selectAdminUser);
  for (const button of document.querySelectorAll("[data-admin-view]")) button.addEventListener("click", () => {
    for (const tab of document.querySelectorAll("[data-admin-view]")) tab.setAttribute("aria-pressed", String(tab === button));
    $("#admin-labs-panel").hidden = button.dataset.adminView !== "labs";
    $("#admin-users-panel").hidden = button.dataset.adminView !== "users";
  });
  $("#admin-create-form").addEventListener("submit", event => {
    event.preventDefault();
    submit(event.currentTarget, async (fields, result) => {
      const response = await request("/users", { method: "POST", body: fields });
      event.target.reset(); await loadUsers(response.user.id);
      result.textContent = `Utente ${response.user.username} creato. Comunica le credenziali all’utente.`;
      showCode(response.recovery_code);
    });
  });
  $("#admin-reset-form").addEventListener("submit", event => {
    event.preventDefault();
    submit(event.currentTarget, async (fields, result) => {
      const id = fields.account_id; delete fields.account_id;
      const response = await request(`/users/${encodeURIComponent(id)}/reset`, { method: "POST", body: fields });
      event.target.reset(); await loadUsers();
      result.textContent = `Account ${response.user.username} aggiornato. Comunica le nuove credenziali all’utente.`;
      showCode(response.recovery_code);
    });
  });
  $("#admin-delete-open").addEventListener("click", () => {
    const user = users.find(user => user.id === $("#admin-users").value);
    if (!user) return;
    const form = $("#admin-delete-form");
    form.reset(); form.elements.account_id.value = user.id;
    form.querySelector(".form-result").textContent = "";
    $("#admin-delete-description").textContent = `Eliminare l’account di ${user.username}? L’utente verrà disconnesso e le sue prenotazioni attive saranno annullate.`;
    $("#admin-delete-dialog").showModal();
  });
  $("#admin-delete-form").addEventListener("submit", event => {
    event.preventDefault();
    submit(event.currentTarget, async fields => {
      await request(`/users/${encodeURIComponent(fields.account_id)}`, { method: "DELETE", body: { admin_password: fields.admin_password } });
      event.target.reset(); $("#admin-delete-dialog").close(); await loadUsers();
      const result = $("#admin-reset-form .form-result");
      result.classList.remove("error"); result.textContent = "Utente eliminato. È stato avviato l’annullamento delle sue prenotazioni attive.";
    });
  });
  $("#admin-delete-dialog").addEventListener("close", () => $("#admin-delete-form").reset());
  $("#manage-dialog").addEventListener("close", () => {
    $("#admin-create-form").reset(); $("#admin-reset-form").reset(); selectAdminUser();
  });
  return {
    get session() { return session; },
    expire() { if (session) setSession(null); },
    loadUsers,
    async restore() {
      try { setSession(await request("/session")); }
      catch (error) { setSession(null); if (!/Accedi|Sessione scaduta/.test(error.message)) $("#login-form .form-result").textContent = error.message; }
    },
  };
}
