import { createContext, useContext, useEffect, useState, ReactNode } from "react";
import { Session, User } from "@supabase/supabase-js";
import { supabase } from "./supabase";

type AuthState = {
  session: Session | null;
  user: User | null;
  isAdmin: boolean;
  loading: boolean;
  signInPassword: (email: string, password: string) => Promise<void>;
  signInMagicLink: (email: string) => Promise<void>;
  sendReset: (email: string) => Promise<void>;
  setPassword: (password: string) => Promise<void>;
  signOut: () => Promise<void>;
};

const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [isAdmin, setIsAdmin] = useState(false);
  const [loading, setLoading] = useState(true);

  async function refreshAdmin(s: Session | null) {
    if (!s) {
      setIsAdmin(false);
      return;
    }
    // own-row RLS on user_roles lets a logged-in user read their own flag.
    const { data } = await supabase
      .from("user_roles")
      .select("is_admin")
      .eq("user_id", s.user.id)
      .maybeSingle();
    setIsAdmin(Boolean(data?.is_admin));
  }

  useEffect(() => {
    let alive = true;
    supabase.auth.getSession().then(async ({ data }) => {
      if (!alive) return;
      setSession(data.session);
      await refreshAdmin(data.session);
      setLoading(false);
    });
    const { data: sub } = supabase.auth.onAuthStateChange((_e, s) => {
      setSession(s);
      refreshAdmin(s);
    });
    return () => {
      alive = false;
      sub.subscription.unsubscribe();
    };
  }, []);

  const origin = typeof window !== "undefined" ? window.location.origin : "";

  const value: AuthState = {
    session,
    user: session?.user ?? null,
    isAdmin,
    loading,
    async signInPassword(email, password) {
      const { error } = await supabase.auth.signInWithPassword({ email, password });
      if (error) throw error;
    },
    async signInMagicLink(email) {
      const { error } = await supabase.auth.signInWithOtp({
        email,
        options: { emailRedirectTo: `${origin}/auth/callback` },
      });
      if (error) throw error;
    },
    async sendReset(email) {
      const { error } = await supabase.auth.resetPasswordForEmail(email, {
        redirectTo: `${origin}/reset`,
      });
      if (error) throw error;
    },
    async setPassword(password) {
      const { error } = await supabase.auth.updateUser({ password });
      if (error) throw error;
    },
    async signOut() {
      await supabase.auth.signOut();
    },
  };

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth must be used within AuthProvider");
  return v;
}
