use anchor_lang::prelude::*;

declare_id!("841hPEnHjRQ7bn4tm6Lk6whxMtt5dCfbJL2Hf5QA6XKv");

#[program]
pub mod course_registry {
    use super::*;

    pub fn register(ctx: Context<Register>, ticket: u64) -> Result<()> {
        ctx.accounts.entry.set_inner(Entry {
            authority: ctx.accounts.authority.key(),
            ticket,
            bump: ctx.bumps.entry,
        });
        Ok(())
    }

    pub fn revise(ctx: Context<Revise>, ticket: u64) -> Result<()> {
        ctx.accounts.entry.ticket = ticket;
        Ok(())
    }
}

#[derive(Accounts)]
pub struct Register<'info> {
    #[account(mut)]
    pub authority: Signer<'info>,
    #[account(init, payer = authority, space = Entry::DISCRIMINATOR.len() + Entry::INIT_SPACE,
              seeds = [b"entry", authority.key().as_ref()], bump)]
    pub entry: Account<'info, Entry>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct Revise<'info> {
    pub authority: Signer<'info>,
    #[account(mut, seeds = [b"entry", authority.key().as_ref()], bump = entry.bump,
              has_one = authority)]
    pub entry: Account<'info, Entry>,
}

#[account]
#[derive(InitSpace)]
pub struct Entry {
    pub authority: Pubkey,
    pub ticket: u64,
    pub bump: u8,
}
