use anchor_lang::prelude::*;
use anchor_lang::system_program;

declare_id!("88HxyoRrb9NzqWfk34SCoqHZcMFxmmHg6XVNpcVPxoFL");

/// PLACEHOLDER: devnet SOL price used for cents→lamports conversion.
/// 1 SOL = 15000 cents ($150). Replace with an oracle feed in production.
const SOL_PRICE_CENTS: u64 = 15_000;
const LAMPORTS_PER_SOL: u64 = 1_000_000_000;

fn cents_to_lamports(cents: u64) -> u64 {
    // lamports = cents * LAMPORTS_PER_SOL / SOL_PRICE_CENTS
    cents
        .checked_mul(LAMPORTS_PER_SOL)
        .unwrap_or(0)
        .checked_div(SOL_PRICE_CENTS)
        .unwrap_or(0)
}

/// On-chain settlement record.
#[account]
#[derive(InitSpace)]
pub struct Settlement {
    pub seller: Pubkey,
    pub kwh_contributed: u64,
    pub final_approved_price: u64,
    pub payout_amount: u64,
    pub period_start: i64,
    pub timestamp: i64,
    pub record_hash: [u8; 32],
    pub direction: Direction,
    pub bump: u8,
}

/// Daily Merkle commitment over all decision hashes made in one UTC day
/// (Phase 5 advanced roadmap). One PDA per (authority, date) — the date is
/// its canonical "YYYY-MM-DD" string, giving a fixed 10-byte seed.
#[account]
#[derive(InitSpace)]
pub struct DailyCommitment {
    pub authority: Pubkey,
    #[max_len(10)]
    pub date: String, // "YYYY-MM-DD" UTC
    pub merkle_root: [u8; 32],
    pub record_count: u32,
    pub committed_at: i64,
    pub bump: u8,
}

#[derive(AnchorSerialize, AnchorDeserialize, InitSpace, Clone, PartialEq, Eq)]
pub enum Direction {
    LocalPool,
    Import,
    Export,
}

impl Default for Direction {
    fn default() -> Self {
        Self::LocalPool
    }
}

#[error_code]
pub enum GridRightError {
    #[msg("Recipient wallet does not match Settlement.seller")]
    SellerMismatch,
    #[msg("Payout amount is zero")]
    ZeroPayout,
    #[msg("Date must be a 10-character YYYY-MM-DD string")]
    InvalidDate,
    #[msg("A commitment must cover at least one record")]
    EmptyCommitment,
}

#[program]
pub mod gridright {
    use super::*;

    pub fn initialize(_ctx: Context<Initialize>) -> Result<()> {
        msg!("GridRight program initialized");
        Ok(())
    }

    /// Record a batched settlement for one seller for one period.
    pub fn settle_period(
        ctx: Context<SettlePeriod>,
        kwh_contributed: u64,
        final_approved_price: u64,
        payout_amount: u64,
        period_start: i64,
        timestamp: i64,
        record_hash: [u8; 32],
        direction: Direction,
    ) -> Result<()> {
        let settlement = &mut ctx.accounts.settlement;
        settlement.seller = ctx.accounts.seller.key();
        settlement.kwh_contributed = kwh_contributed;
        settlement.final_approved_price = final_approved_price;
        settlement.payout_amount = payout_amount;
        settlement.period_start = period_start;
        settlement.timestamp = timestamp;
        settlement.record_hash = record_hash;
        settlement.direction = direction;
        settlement.bump = ctx.bumps.settlement;
        Ok(())
    }

    /// Transfer SOL payout from operator to seller.
    ///
    /// Verifies that `seller_wallet` matches `settlement.seller` before
    /// transferring. Converts `settlement.payout_amount` (cents) to lamports
    /// using the PLACEHOLDER SOL price constant above.
    pub fn pay_seller(ctx: Context<PaySeller>) -> Result<()> {
        let settlement = &ctx.accounts.settlement;

        require!(
            ctx.accounts.seller_wallet.key() == settlement.seller,
            GridRightError::SellerMismatch
        );
        require!(settlement.payout_amount > 0, GridRightError::ZeroPayout);

        let lamports = cents_to_lamports(settlement.payout_amount);

        let cpi_ctx = CpiContext::new(
            ctx.accounts.system_program.to_account_info(),
            system_program::Transfer {
                from: ctx.accounts.operator.to_account_info(),
                to: ctx.accounts.seller_wallet.to_account_info(),
            },
        );
        system_program::transfer(cpi_ctx, lamports)?;

        msg!(
            "Paid {} lamports ({} cents) to seller {}",
            lamports,
            settlement.payout_amount,
            settlement.seller
        );
        Ok(())
    }

    /// Commit the Merkle root of one UTC day's decision hashes (Phase 5).
    /// `init` (not init_if_needed) makes the commitment immutable: a second
    /// commit for the same (authority, date) fails — audit trails don't get
    /// silently rewritten.
    pub fn commit_daily_root(
        ctx: Context<CommitDailyRoot>,
        date: String,
        merkle_root: [u8; 32],
        record_count: u32,
    ) -> Result<()> {
        require!(date.len() == 10, GridRightError::InvalidDate);
        require!(record_count > 0, GridRightError::EmptyCommitment);

        let commitment = &mut ctx.accounts.commitment;
        commitment.authority = ctx.accounts.authority.key();
        commitment.date = date;
        commitment.merkle_root = merkle_root;
        commitment.record_count = record_count;
        commitment.committed_at = Clock::get()?.unix_timestamp;
        commitment.bump = ctx.bumps.commitment;
        Ok(())
    }
}

#[derive(Accounts)]
pub struct Initialize {}

#[derive(Accounts)]
#[instruction(
    kwh_contributed: u64,
    final_approved_price: u64,
    payout_amount: u64,
    period_start: i64,
    timestamp: i64,
    record_hash: [u8; 32],
    direction: Direction,
)]
pub struct SettlePeriod<'info> {
    #[account(
        init,
        payer = authority,
        space = 8 + Settlement::INIT_SPACE,
        seeds = [
            b"settlement",
            seller.key().as_ref(),
            &period_start.to_le_bytes(),
        ],
        bump,
    )]
    pub settlement: Account<'info, Settlement>,
    /// CHECK: seller is a pubkey seed only — no data is read or written
    pub seller: UncheckedAccount<'info>,
    #[account(mut)]
    pub authority: Signer<'info>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
#[instruction(date: String, merkle_root: [u8; 32], record_count: u32)]
pub struct CommitDailyRoot<'info> {
    #[account(
        init,
        payer = authority,
        space = 8 + DailyCommitment::INIT_SPACE,
        seeds = [
            b"daily_commitment",
            authority.key().as_ref(),
            date.as_bytes(),
        ],
        bump,
    )]
    pub commitment: Account<'info, DailyCommitment>,
    #[account(mut)]
    pub authority: Signer<'info>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct PaySeller<'info> {
    pub settlement: Account<'info, Settlement>,
    /// CHECK: verified in instruction body against settlement.seller
    #[account(mut)]
    pub seller_wallet: UncheckedAccount<'info>,
    #[account(mut)]
    pub operator: Signer<'info>,
    pub system_program: Program<'info, System>,
}
