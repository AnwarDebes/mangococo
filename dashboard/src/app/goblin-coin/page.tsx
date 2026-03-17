"use client";

import { useState, useEffect } from "react";
import {
  Wallet,
  ExternalLink,
  Copy,
  Check,
  TrendingUp,
  Users,
  BarChart3,
  Shield,
  Zap,
  Globe,
} from "lucide-react";
import GoblinCoin3D from "@/components/3d/GoblinCoin3D";

function StatBox({
  label,
  value,
  icon: Icon,
  accent = false,
}: {
  label: string;
  value: string;
  icon: React.ElementType;
  accent?: boolean;
}) {
  return (
    <div className="card-hover hover-glow">
      <div className="flex items-center gap-3">
        <div
          className={`flex h-10 w-10 items-center justify-center rounded-lg ${
            accent
              ? "bg-gold-500/10 text-gold-400"
              : "bg-goblin-500/10 text-goblin-400"
          }`}
        >
          <Icon size={20} />
        </div>
        <div>
          <p className="text-xs text-gray-500">{label}</p>
          <p className={`text-lg font-bold ${accent ? "value-gold" : "text-white"}`}>
            {value}
          </p>
        </div>
      </div>
    </div>
  );
}

function StepCard({
  step,
  title,
  description,
}: {
  step: number;
  title: string;
  description: string;
}) {
  return (
    <div className="card-hover hover-glow group">
      <div className="flex items-start gap-4">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-goblin-500/20 text-goblin-400 text-sm font-bold group-hover:bg-goblin-500 group-hover:text-white transition-colors">
          {step}
        </div>
        <div>
          <h4 className="font-semibold text-white">{title}</h4>
          <p className="mt-1 text-sm text-gray-400">{description}</p>
        </div>
      </div>
    </div>
  );
}

function ResponsiveCoin() {
  const [coinSize, setCoinSize] = useState(240);

  useEffect(() => {
    const update = () => setCoinSize(window.innerWidth < 640 ? 150 : 240);
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);

  return <GoblinCoin3D size={coinSize} />;
}

export default function GoblinCoinPage() {
  const [copied, setCopied] = useState(false);
  const contractAddress = "0x...your-contract-address";

  const handleCopy = () => {
    navigator.clipboard.writeText(contractAddress);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="space-y-6 sm:space-y-8">
      {/* Hero Section */}
      <div className="relative particles-bg rounded-xl sm:rounded-2xl border border-goblin-500/10 bg-gradient-to-br from-goblin-900/30 via-gray-900 to-gray-950 p-4 sm:p-8 overflow-hidden">
        <div className="relative z-10 flex flex-col items-center text-center lg:flex-row lg:text-left lg:justify-between">
          <div className="lg:max-w-lg">
            <div className="flex items-center justify-center lg:justify-start gap-2 mb-2">
              <span className="text-xs font-bold bg-goblin-500/20 text-goblin-400 px-3 py-1 rounded-full">
                LIVE ON BLOCKCHAIN
              </span>
            </div>
            <h1 className="text-2xl sm:text-4xl font-bold text-white mb-2">
              <span className="text-goblin-gradient">GBLN</span> Token
            </h1>
            <p className="text-sm sm:text-lg text-gray-400 mb-4">
              The official token of Goblin AI Trading Platform
            </p>
            <p className="text-xs sm:text-sm text-gray-500 max-w-md">
              GBLN powers the Goblin ecosystem — staking rewards, premium features,
              and governance for the AI trading community.
            </p>

            {/* Contract Address */}
            <div className="mt-6 flex items-center gap-2 flex-wrap justify-center lg:justify-start">
              <span className="text-xs text-gray-500">Contract:</span>
              <button
                onClick={handleCopy}
                className="flex items-center gap-1.5 rounded-lg bg-gray-800/50 border border-gray-700 px-3 py-1.5 text-xs font-mono text-gray-300 hover:border-goblin-500/30 transition-colors"
              >
                {contractAddress}
                {copied ? (
                  <Check size={12} className="text-goblin-500" />
                ) : (
                  <Copy size={12} className="text-gray-500" />
                )}
              </button>
            </div>

            {/* Action Buttons */}
            <div className="mt-6 flex gap-3 flex-wrap justify-center lg:justify-start">
              <button className="btn-metamask">
                <Wallet size={18} />
                Connect MetaMask
              </button>
              <button className="btn-goblin flex items-center gap-2">
                <ExternalLink size={16} />
                View on Explorer
              </button>
            </div>
          </div>

          {/* 3D Coin — single responsive instance */}
          <div className="mt-6 lg:mt-0">
            <div className="relative">
              <div className="absolute inset-0 bg-goblin-500/10 blur-3xl rounded-full" />
              <ResponsiveCoin />
            </div>
          </div>
        </div>
      </div>

      {/* Token Stats */}
      <div>
        <h2 className="section-title mb-4">Token Statistics</h2>
        <div className="grid grid-cols-2 gap-2 sm:gap-4 lg:grid-cols-4">
          <StatBox label="Market Cap" value="--" icon={BarChart3} accent />
          <StatBox label="Holders" value="--" icon={Users} />
          <StatBox label="24h Volume" value="--" icon={TrendingUp} accent />
          <StatBox label="Total Supply" value="--" icon={Globe} />
        </div>
      </div>

      {/* Token Info */}
      <div className="grid gap-4 sm:gap-6 lg:grid-cols-2">
        {/* Token Details */}
        <div className="card">
          <h3 className="section-title mb-4">Token Information</h3>
          <div className="space-y-3">
            {[
              { label: "Token Name", value: "Goblin" },
              { label: "Symbol", value: "GBLN" },
              { label: "Network", value: "Base" },
              { label: "Decimals", value: "18" },
              { label: "Type", value: "ERC-20" },
            ].map((item) => (
              <div
                key={item.label}
                className="flex items-center justify-between border-b border-gray-800/50 pb-2 last:border-0"
              >
                <span className="text-sm text-gray-500">{item.label}</span>
                <span className="text-sm font-medium text-white">{item.value}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Wallet Section */}
        <div className="card">
          <h3 className="section-title mb-4">Your Wallet</h3>
          <div className="flex flex-col items-center justify-center py-6 text-center">
            <div className="flex h-16 w-16 items-center justify-center rounded-full bg-gray-800 border border-gray-700 mb-4">
              <Wallet size={28} className="text-gray-500" />
            </div>
            <p className="text-sm text-gray-400 mb-1">
              Connect your wallet to view your GBLN balance
            </p>
            <p className="text-xs text-gray-600 mb-4">
              MetaMask, WalletConnect, and more supported
            </p>
            <button className="btn-metamask text-sm">
              <Wallet size={16} />
              Connect Wallet
            </button>
          </div>
        </div>
      </div>

      {/* Price Chart Placeholder */}
      <div className="card">
        <h3 className="section-title mb-4">GBLN Price Chart</h3>
        <div className="flex h-[300px] items-center justify-center rounded-lg border border-goblin-500/10 bg-gray-950">
          <div className="text-center text-gray-500">
            <TrendingUp size={32} className="mx-auto mb-2 text-goblin-500/30" />
            <p className="text-sm font-medium">Price chart coming soon</p>
            <p className="mt-1 text-xs text-gray-600">
              Live price tracking will be available after DEX listing
            </p>
          </div>
        </div>
      </div>

      {/* Features / Use Cases */}
      <div>
        <h2 className="section-title mb-4">GBLN Utility</h2>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <div className="card-hover hover-glow">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-goblin-500/10 text-goblin-400 mb-3">
              <Zap size={20} />
            </div>
            <h4 className="font-semibold text-white">Premium Trading</h4>
            <p className="mt-1 text-sm text-gray-400">
              Stake GBLN to unlock advanced AI trading signals and strategies
            </p>
          </div>
          <div className="card-hover hover-glow">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-gold-500/10 text-gold-400 mb-3">
              <Shield size={20} />
            </div>
            <h4 className="font-semibold text-white">Governance</h4>
            <p className="mt-1 text-sm text-gray-400">
              Vote on platform upgrades, trading pairs, and fee structures
            </p>
          </div>
          <div className="card-hover hover-glow">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-goblin-500/10 text-goblin-400 mb-3">
              <TrendingUp size={20} />
            </div>
            <h4 className="font-semibold text-white">Staking Rewards</h4>
            <p className="mt-1 text-sm text-gray-400">
              Earn passive income by staking GBLN tokens in the ecosystem
            </p>
          </div>
        </div>
      </div>

      {/* How to Buy */}
      <div>
        <h2 className="section-title mb-4">How to Get GBLN</h2>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StepCard
            step={1}
            title="Get a Wallet"
            description="Install MetaMask or any Web3 wallet on your browser"
          />
          <StepCard
            step={2}
            title="Add Funds"
            description="Buy ETH or BNB and transfer to your wallet"
          />
          <StepCard
            step={3}
            title="Connect & Swap"
            description="Connect to a DEX like Uniswap and swap for GBLN"
          />
          <StepCard
            step={4}
            title="Hold & Earn"
            description="Stake your GBLN tokens to earn rewards and access premium features"
          />
        </div>
      </div>
    </div>
  );
}
