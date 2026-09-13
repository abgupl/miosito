const API_URL = "https://miosito-production.up.railway.app/api/offerte";

let offerte = [];
let canaleAttivo = "tutte";

const lista = document.querySelector("#lista-offerte");
const stato = document.querySelector("#stato");
const ricerca = document.querySelector("#ricerca");

function euro(valore) {
  if (!valore || valore === "NO") return null;
  const numero = Number(String(valore).replace(/[^0-9,.-]/g, "").replace(",", "."));
  return Number.isFinite(numero)
    ? new Intl.NumberFormat("it-IT", { style: "currency", currency: "EUR" }).format(numero)
    : valore;
}

function dataItaliana(valore) {
  const data = new Date(valore);
  if (Number.isNaN(data.getTime())) return "Appena pubblicata";
  return new Intl.DateTimeFormat("it-IT", {
    day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit"
  }).format(data);
}

function cardOfferta(offerta) {
  const prezzo = euro(offerta.prezzo) || "Vedi prezzo";
  const vecchioPrezzo = euro(offerta.vecchio_prezzo);
  const foto = offerta.immagine
    ? `<img src="${offerta.immagine}" alt="" loading="lazy" onerror="this.hidden=true; this.parentElement.classList.add('image-failed')">`
    : `<span class="placeholder">${offerta.canale === "casa" ? "🏠" : "⚡"}</span>`;
  const sconto = offerta.sconto ? `<b class="discount">-${offerta.sconto}%</b>` : "";
  const telegram = offerta.telegram_url
    ? `<a class="telegram-link" href="${offerta.telegram_url}" target="_blank" rel="noreferrer" aria-label="Apri il post Telegram">➤</a>`
    : "";

  return `<article class="offer-card">
    <div class="offer-image">${foto}${sconto}<span class="channel ${offerta.canale}">${offerta.canale === "casa" ? "Casa" : "Tech"}</span></div>
    <div class="offer-body">
      <p class="meta">◷ ${dataItaliana(offerta.pubblicata_il)} · ${offerta.categoria || "Offerta"}</p>
      <h3>${offerta.nome}</h3>
      <div class="price-row"><strong>${prezzo}</strong>${vecchioPrezzo && vecchioPrezzo !== prezzo ? `<del>${vecchioPrezzo}</del>` : ""}</div>
      <div class="card-actions"><a class="amazon-button" href="${offerta.link}" target="_blank" rel="sponsored noreferrer">Vedi su Amazon ↗</a>${telegram}</div>
    </div>
  </article>`;
}

function mostraOfferte() {
  const testo = ricerca.value.trim().toLowerCase();
  const visibili = offerte.filter(offerta =>
    (canaleAttivo === "tutte" || offerta.canale === canaleAttivo) &&
    (!testo || `${offerta.nome} ${offerta.categoria || ""}`.toLowerCase().includes(testo))
  );

  if (!visibili.length) {
    lista.hidden = true;
    stato.hidden = false;
    stato.textContent = "Nessuna offerta con questi filtri.";
    return;
  }
  stato.hidden = true;
  lista.hidden = false;
  lista.innerHTML = visibili.map(cardOfferta).join("");
}

async function aggiornaOfferte() {
  try {
    const risposta = await fetch(API_URL, { cache: "no-store" });
    if (!risposta.ok) throw new Error("Servizio non disponibile");
    const dati = await risposta.json();
    offerte = Array.isArray(dati.offerte) ? dati.offerte : [];
    document.querySelector("#totale-offerte").textContent = offerte.length;
    document.querySelector("#ultimo-aggiornamento").textContent = `Aggiornato ${dataItaliana(dati.aggiornato_il)}`;
    mostraOfferte();
  } catch {
    lista.hidden = true;
    stato.hidden = false;
    stato.textContent = "Le offerte non sono disponibili in questo momento. Riprova tra poco.";
  }
}

document.querySelectorAll("[data-canale]").forEach(pulsante => {
  pulsante.addEventListener("click", () => {
    canaleAttivo = pulsante.dataset.canale;
    document.querySelectorAll("[data-canale]").forEach(elemento => elemento.classList.remove("active"));
    pulsante.classList.add("active");
    mostraOfferte();
  });
});

ricerca.addEventListener("input", mostraOfferte);
aggiornaOfferte();
setInterval(aggiornaOfferte, 60_000);
