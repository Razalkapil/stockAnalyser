-- Rights issues: store the subscription premium the subject already carries.
--
-- A rights issue moves the price, but unlike a split or a bonus its factor is NOT a function of
-- the ratio alone: new shares are issued at a set price, so the dilution depends on how far
-- below the market that price sits. The subject states both halves of what is needed
-- ("Rights 3:19 @ Premium Rs 74/-") -- everything except the cum-rights close, which lives in
-- the price lake, not here.
--
-- So the parser records the PREMIUM (over face value, as printed) and leaves price_factor NULL,
-- and ingest.adjustments computes the theoretical ex-rights factor where it can see both the
-- face value as of the ex-date and the last close before it. Storing the premium rather than an
-- issue price keeps the parser honest: the face value it would have to be added to is nowhere
-- in the subject, and guessing one would invent a discount.
--
-- Until this, all 218 stored rights actions were `ambiguous` and excluded from the adjusted
-- series -- a phantom ex-date drop in 68 symbols the backtests actually trade.

ALTER TABLE corporate_actions ADD COLUMN issue_premium REAL;
