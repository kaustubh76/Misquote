"use client";

/**
 * The wagmi and react-query providers, wrapping the whole app.
 *
 * `QueryClient` is built inside a `useState` initialiser rather than at module
 * scope. At module scope one client is shared by every render pass of a static
 * export, which leaks one visitor's cached reads into the next render — and
 * with `isValidKey` in that cache, the leak would be someone else's key state.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { WagmiProvider } from "wagmi";
import { config } from "@/lib/wagmi";

export function WalletProvider({ children }: { children: ReactNode }) {
  const [queryClient] = useState(() => new QueryClient());

  return (
    <WagmiProvider config={config}>
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    </WagmiProvider>
  );
}
