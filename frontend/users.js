/* Account administration. Authorization is also enforced by the API. */
(() => {
  function report(text) {
    document.querySelector("#users-message").textContent = text;
  }
  function handleError(error) {
    if (error.status === 401) showLogin("Sua sessão expirou. Entre novamente.");
    else report(error.message);
  }
  function busy(card, value) {
    for (const button of card.querySelectorAll("button")) button.disabled = value;
  }
  function inputLabel(text, options) {
    const label = document.createElement("label");
    label.textContent = text;
    const input = document.createElement("input");
    Object.assign(input, options);
    label.append(input);
    return [label, input];
  }
  function accountCard(account) {
    const card = document.createElement("article");
    card.className = "user-card";
    card.dataset.accountId = account.id;
    const header = document.createElement("div");
    header.className = "source-card-header";
    const title = document.createElement("h3");
    title.textContent = account.username;
    const badge = document.createElement("span");
    badge.className = account.status === "ACTIVE" ? "enabled-badge" : "disabled-badge";
    badge.textContent = `${account.role === "ADMIN" ? "Administrador" : "Usuário"} · ${account.status === "ACTIVE" ? "Ativo" : "Bloqueado"}`;
    header.append(title, badge);
    const form = document.createElement("form");
    form.className = "user-edit-form";
    const [nameLabel, name] = inputLabel("Nome de acesso", {name:"username", value:account.username, maxLength:80, required:true, autoComplete:"off"});
    const [passwordLabel, password] = inputLabel("Nova senha (opcional)", {name:"password", type:"password", minLength:12, maxLength:256, autoComplete:"new-password"});
    const [repeatLabel, repeat] = inputLabel("Repita a nova senha", {name:"repeat", type:"password", minLength:12, maxLength:256, autoComplete:"new-password"});
    const fields = document.createElement("div");
    fields.className = "user-edit-fields";
    fields.append(nameLabel, passwordLabel, repeatLabel);
    const actions = document.createElement("div");
    actions.className = "user-actions";
    const save = document.createElement("button");
    save.type = "submit"; save.className = "button button-secondary"; save.textContent = "Salvar alterações";
    actions.append(save);
    if (account.role === "USER") {
      const toggle = document.createElement("button");
      toggle.type = "button"; toggle.className = "button button-quiet";
      toggle.textContent = account.status === "ACTIVE" ? "Bloquear acesso" : "Reativar acesso";
      toggle.addEventListener("click", async () => {
        const disabling = account.status === "ACTIVE";
        if (disabling && !window.confirm(`Bloquear o acesso de ${account.username}? As sessões abertas serão encerradas.`)) return;
        busy(card, true);
        try {
          await api(`/api/admin/accounts/${encodeURIComponent(account.id)}`, {method:"PATCH", body:JSON.stringify({status:disabling ? "DISABLED" : "ACTIVE"})});
          report(disabling ? "Acesso bloqueado e sessões encerradas." : "Acesso reativado. O usuário pode entrar novamente.");
          await refreshUsers();
        } catch (error) { handleError(error); }
        finally { busy(card, false); }
      });
      const remove = document.createElement("button");
      remove.type = "button"; remove.className = "button button-danger"; remove.textContent = "Excluir usuário";
      remove.addEventListener("click", async () => {
        if (!window.confirm(`Excluir ${account.username}? O acesso será removido e o histórico de auditoria será preservado.`)) return;
        busy(card, true);
        try {
          await api(`/api/admin/accounts/${encodeURIComponent(account.id)}`, {method:"DELETE"});
          report("Usuário excluído. O nome de acesso e a vaga estão disponíveis novamente.");
          await refreshUsers();
        } catch (error) { handleError(error); }
        finally { busy(card, false); }
      });
      actions.append(toggle, remove);
    }
    const note = document.createElement("p");
    note.className = "small muted";
    note.textContent = account.role === "ADMIN"
      ? "Administrador protegido: esta conta pode editar nome e senha, mas não pode ser bloqueada nem excluída. Alterar seus dados exige novo login."
      : "Deixe a senha vazia para mantê-la. Alterar nome ou senha encerra as sessões deste usuário.";
    form.append(fields, actions, note);
    form.addEventListener("submit", async event => {
      event.preventDefault();
      if (password.value !== repeat.value) { report("A nova senha e a confirmação devem ser iguais."); return; }
      if (!name.value.trim()) { report("Informe um nome de acesso."); return; }
      const changes = {};
      if (name.value.trim() !== account.username) changes.username = name.value.trim();
      if (password.value) changes.password = password.value;
      if (!Object.keys(changes).length) { report("Nenhuma alteração para salvar."); return; }
      busy(card, true);
      try {
        const saved = await api(`/api/admin/accounts/${encodeURIComponent(account.id)}`, {method:"PATCH", body:JSON.stringify(changes)});
        password.value = ""; repeat.value = "";
        if (saved.id === state.account?.id && saved.sessions_revoked) {
          showLogin("Seus dados foram alterados. Entre novamente com o nome e a senha atuais.");
          return;
        }
        report("Alterações salvas.");
        await refreshUsers();
      } catch (error) { handleError(error); }
      finally { busy(card, false); }
    });
    card.append(header, form);
    return card;
  }
  async function refreshUsers() {
    if (state.account?.role !== "ADMIN") return;
    const list = document.querySelector("#users-list");
    list.textContent = "Carregando contas...";
    try {
      const accounts = await api("/api/admin/accounts");
      // A pending response must not repopulate private data after logout.
      if (state.account?.role !== "ADMIN") return;
      list.replaceChildren(...accounts.map(accountCard));
      const users = accounts.filter(account => account.role === "USER").length;
      document.querySelector("#users-count").textContent = `${users} / 4 usuários`;
      document.querySelector("#create-user-submit").disabled = users >= 4;
    } catch (error) {
      list.textContent = "Não foi possível carregar as contas.";
      handleError(error);
    }
  }
  document.querySelector("#users-refresh").addEventListener("click", refreshUsers);
  document.querySelector("#create-user-form").addEventListener("submit", async event => {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    if (data.get("password") !== data.get("repeat")) { report("A senha e a confirmação devem ser iguais."); return; }
    if (!String(data.get("username")).trim()) { report("Informe um nome de acesso."); return; }
    document.querySelector("#create-user-submit").disabled = true;
    try {
      await api("/api/admin/accounts", {method:"POST", body:JSON.stringify({username:String(data.get("username")).trim(), password:data.get("password")})});
      form.reset(); report("Usuário criado. Ele já pode entrar com a senha definida.");
      await refreshUsers();
    } catch (error) { handleError(error); }
    finally { if (state.account) document.querySelector("#create-user-submit").disabled = document.querySelectorAll("#users-list .user-card").length >= 5; }
  });
  window.StormTrackUsers = {
    refresh:refreshUsers,
    clear() {
      document.querySelector("#users-list").replaceChildren();
      document.querySelector("#create-user-form").reset();
      report("");
    },
  };
})();
