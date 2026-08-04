export const AUTH_TOKEN_STORAGE_KEY = 'wikiAuthToken';
export const AUTH_USERNAME_STORAGE_KEY = 'wikiUsername';
export const AUTH_ROLE_STORAGE_KEY = 'wikiUserRole';
export const AUTH_EXPIRED_EVENT = 'wiki-auth-expired';

const LEGACY_AUTH_TOKEN_STORAGE_KEY = 'adminToken';
const LEGACY_USERNAME_STORAGE_KEY = 'username';
const LEGACY_ROLE_STORAGE_KEY = 'userRole';
const AUTH_FETCH_PATCH_KEY = '__wikiAuthFetchPatched__';

export type StoredAuthSession = {
    token: string;
    username?: string | null;
    role?: string | null;
};

function readSessionStorage(key: string): string | null {
    if (typeof window === 'undefined') {
        return null;
    }

    try {
        return window.sessionStorage.getItem(key);
    } catch {
        return null;
    }
}

function writeSessionStorage(key: string, value: string) {
    if (typeof window === 'undefined') {
        return;
    }

    try {
        window.sessionStorage.setItem(key, value);
    } catch {
        // 说明：隐私模式或存储被禁用时，调用方会在后续鉴权请求中自然失败。
    }
}

function removeSessionStorage(key: string) {
    if (typeof window === 'undefined') {
        return;
    }

    try {
        window.sessionStorage.removeItem(key);
    } catch {
        // 说明：清理本地会话失败不应阻断登出流程或页面跳转。
    }
}

export function getAuthToken(): string | null {
    const token = readSessionStorage(AUTH_TOKEN_STORAGE_KEY);
    if (token) {
        return token;
    }

    const legacyToken = readSessionStorage(LEGACY_AUTH_TOKEN_STORAGE_KEY);
    if (!legacyToken) {
        return null;
    }

    // 说明：兼容旧会话一次性迁移到新的数据库用户 JWT 存储键，迁移后移除旧 adminToken。
    writeSessionStorage(AUTH_TOKEN_STORAGE_KEY, legacyToken);
    removeSessionStorage(LEGACY_AUTH_TOKEN_STORAGE_KEY);
    return legacyToken;
}

export function getAuthRole(): string | null {
    const role = readSessionStorage(AUTH_ROLE_STORAGE_KEY);
    if (role) {
        return role;
    }

    const legacyRole = readSessionStorage(LEGACY_ROLE_STORAGE_KEY);
    if (!legacyRole) {
        return null;
    }

    // 说明：角色只用于前端导航分流，真正权限仍由后端根据数据库用户校验。
    writeSessionStorage(AUTH_ROLE_STORAGE_KEY, legacyRole);
    removeSessionStorage(LEGACY_ROLE_STORAGE_KEY);
    return legacyRole;
}

export function saveAuthSession(session: StoredAuthSession) {
    writeSessionStorage(AUTH_TOKEN_STORAGE_KEY, session.token);

    if (session.username) {
        writeSessionStorage(AUTH_USERNAME_STORAGE_KEY, session.username);
    }
    if (session.role) {
        writeSessionStorage(AUTH_ROLE_STORAGE_KEY, session.role);
    }

    // 说明：旧版使用 adminToken 命名，现在统一改为 wikiAuthToken，避免继续暗示静态管理员 Token。
    removeSessionStorage(LEGACY_AUTH_TOKEN_STORAGE_KEY);
    removeSessionStorage(LEGACY_USERNAME_STORAGE_KEY);
    removeSessionStorage(LEGACY_ROLE_STORAGE_KEY);
}

export function clearAuthSession() {
    removeSessionStorage(AUTH_TOKEN_STORAGE_KEY);
    removeSessionStorage(AUTH_USERNAME_STORAGE_KEY);
    removeSessionStorage(AUTH_ROLE_STORAGE_KEY);
    removeSessionStorage(LEGACY_AUTH_TOKEN_STORAGE_KEY);
    removeSessionStorage(LEGACY_USERNAME_STORAGE_KEY);
    removeSessionStorage(LEGACY_ROLE_STORAGE_KEY);
}

export function buildAuthHeaders(): HeadersInit {
    const token = getAuthToken();
    return token ? { Authorization: `Bearer ${token}` } : {};
}

function isLoginPage() {
    return typeof window !== 'undefined' && window.location.pathname.startsWith('/login');
}

function shouldHandleUnauthorizedRequest(input: Parameters<typeof fetch>[0]) {
    if (typeof window === 'undefined') {
        return false;
    }

    try {
        const rawUrl = typeof input === 'string'
            ? input
            : input instanceof URL
                ? input.toString()
                : input.url;
        const url = new URL(rawUrl, window.location.origin);

        // 说明：只处理当前站点的受保护 API，避免登录失败或第三方请求触发错误跳转。
        return url.origin === window.location.origin
            && url.pathname.startsWith('/api/')
            && !url.pathname.startsWith('/api/auth/login');
    } catch {
        return false;
    }
}

export function redirectToLoginAfterAuthExpired() {
    if (typeof window === 'undefined' || isLoginPage()) {
        return;
    }

    clearAuthSession();
    window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT));

    const currentPath = `${window.location.pathname}${window.location.search}`;
    const next = encodeURIComponent(currentPath);
    // 说明：JWT 已失效时使用 replace，避免用户点击返回后又回到必然 401 的页面。
    window.location.replace(`/login?expired=1&next=${next}`);
}

export function handleUnauthorizedResponse(response: Response) {
    if (response.status !== 401) {
        return false;
    }

    redirectToLoginAfterAuthExpired();
    return true;
}

export function installAuthExpirationHandler() {
    if (typeof window === 'undefined') {
        return;
    }

    const patchedWindow = window as typeof window & {
        [AUTH_FETCH_PATCH_KEY]?: boolean;
    };
    if (patchedWindow[AUTH_FETCH_PATCH_KEY]) {
        return;
    }

    const originalFetch = window.fetch.bind(window);
    patchedWindow[AUTH_FETCH_PATCH_KEY] = true;

    window.fetch = async (input, init) => {
        const response = await originalFetch(input, init);
        if (shouldHandleUnauthorizedRequest(input)) {
            handleUnauthorizedResponse(response);
        }
        return response;
    };
}
