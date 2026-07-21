"use client";

import { ConnectionProvider, WalletProvider } from "@solana/wallet-adapter-react";
import { WalletModalProvider } from "@solana/wallet-adapter-react-ui";
import "@solana/wallet-adapter-react-ui/styles.css";

// Devnet RPC endpoint. Override with NEXT_PUBLIC_SOLANA_RPC for a paid RPC.
const DEVNET_RPC =
  process.env.NEXT_PUBLIC_SOLANA_RPC ?? "https://api.devnet.solana.com";

// Empty wallet list on purpose: modern Phantom (and other Wallet Standard
// wallets) auto-register themselves with wallet-adapter. Passing an explicit
// PhantomWalletAdapter here registers it a SECOND time, which triggers the
// "Phantom was registered as a Standard Wallet" warning and can leave the
// connect button unable to open/connect. Let the standard do the detection.
export function WalletProviders({ children }: { children: React.ReactNode }) {
  return (
    <ConnectionProvider endpoint={DEVNET_RPC}>
      <WalletProvider wallets={[]} autoConnect>
        <WalletModalProvider>{children}</WalletModalProvider>
      </WalletProvider>
    </ConnectionProvider>
  );
}
