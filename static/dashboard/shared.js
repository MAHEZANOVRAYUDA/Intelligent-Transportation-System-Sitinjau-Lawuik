const apiHost = window.location.hostname || "localhost";
const isDevServer = window.location.protocol === "file:" || (window.location.port !== "" && window.location.port !== "8000");
const API_BASE = isDevServer ? `http://${apiHost === '127.0.0.1' ? 'localhost' : apiHost}:8000` : window.location.origin;
const WS_URL = isDevServer ? `ws://${apiHost === '127.0.0.1' ? 'localhost' : apiHost}:8000/ws/live` : `ws://${window.location.host}/ws/live`;

// --- Authentication Utilities ---

function getAuthToken() {
    return localStorage.getItem('auth_token');
}

function setAuthToken(token) {
    localStorage.setItem('auth_token', token);
}

function logout() {
    localStorage.removeItem('auth_token');
    window.location.href = 'login.html';
}

function requireAuth() {
    if (!getAuthToken()) {
        window.location.href = 'login.html';
    }
}

/**
 * Wrapper for fetch that automatically adds the API key header.
 * If a request returns 401 Unauthorized, it redirects to login.
 */
async function apiFetch(url, options = {}) {
    const token = getAuthToken();
    const headers = {
        ...options.headers,
    };
    if (token) {
        headers['X-API-Key'] = token;
    }
    
    try {
        const response = await fetch(url, { ...options, headers });
        if (response.status === 401) {
            logout();
            throw new Error("Sesi telah habis, silakan login kembali.");
        }
        return response;
    } catch (error) {
        console.error("API Fetch Error:", error);
        throw error;
    }
}

// --- General Utilities ---

function formatAngka(angka) {
  return new Intl.NumberFormat('id-ID').format(angka);
}

function blendColor(c1, c2, p) {
  const hex2rgb = (hex) => [parseInt(hex.slice(1,3),16), parseInt(hex.slice(3,5),16), parseInt(hex.slice(5,7),16)];
  const [r1, g1, b1] = hex2rgb(c1);
  const [r2, g2, b2] = hex2rgb(c2);
  const r = Math.round(r1 + (r2 - r1) * p);
  const g = Math.round(g1 + (g2 - g1) * p);
  const b = Math.round(b1 + (b2 - b1) * p);
  return `#${r.toString(16).padStart(2,'0')}${g.toString(16).padStart(2,'0')}${b.toString(16).padStart(2,'0')}`;
}

function interpolasiWarnaKapasitas(persen, ambangLancar = 44, ambangPadat = 84) {
  if (persen <= 0) return "#10b981"; // lancar (hijau)
  if (persen < ambangLancar) {
    const p = persen / ambangLancar;
    return blendColor("#10b981", "#f59e0b", p);
  }
  if (persen < ambangPadat) {
    const p = (persen - ambangLancar) / (ambangPadat - ambangLancar);
    return blendColor("#f59e0b", "#ef4444", p);
  }
  return "#ef4444"; // macet (merah)
}
