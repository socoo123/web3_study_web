// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

// One immutable observation per local feed. This is not a Chainlink interface.
contract TeachingPrice {
    bool private immutable published;
    uint64 private immutable answer;
    uint8 private immutable digits;
    uint256 private immutable updatedAt;

    constructor(bool present, uint64 raw, uint8 decimals_, uint32 ageSeconds) {
        published = present;
        answer = present ? raw : 0;
        digits = decimals_;
        updatedAt = present ? block.timestamp - ageSeconds : 0;
    }

    function quote() external view returns (bool, uint64, uint8, uint256) {
        return (published, answer, digits, updatedAt);
    }
}

// One synthetic position, denominated in COL and NOTE. No borrow, swap or token custody.
contract RiskView {
    enum State { Ready, NoDebt, Missing, BadAnswer, BadTime, Stale }
    enum Side { Neither, Collateral, Debt }
    struct Metrics {
        uint256 collateralQ8;
        uint256 debtQ8;
        uint256 adjustedQ8;
        uint256 hfWad;
        uint256 headroomQ8;
    }

    uint8 private constant COL_DIGITS = 18;
    uint8 private constant NOTE_DIGITS = 6;
    uint8 private constant Q_DIGITS = 8;
    uint256 private constant Q_SCALE = uint256(10) ** Q_DIGITS;
    uint16 private constant LTV_BPS = 6500;
    uint16 private constant LT_BPS = 7500;
    uint32 private constant MAX_AGE = 300;
    uint256 private constant BPS = 10_000;

    uint96 private immutable collateral;
    uint96 private immutable debt;
    TeachingPrice private immutable colFeed;
    TeachingPrice private immutable noteFeed;

    constructor(uint96 colRaw, uint96 noteRaw, uint64 colPriceRaw, uint32 colAge, Side missing) {
        collateral = colRaw;
        debt = noteRaw;
        colFeed = new TeachingPrice(missing != Side.Collateral, colPriceRaw, 8, colAge);
        noteFeed = new TeachingPrice(missing != Side.Debt, 1_250_000, 6, 0);
    }

    function position() external view returns (uint96, uint96, TeachingPrice, TeachingPrice) {
        return (collateral, debt, colFeed, noteFeed);
    }

    function policy() external pure returns (uint8, uint8, uint8, uint16, uint16, uint32) {
        return (COL_DIGITS, NOTE_DIGITS, Q_DIGITS, LTV_BPS, LT_BPS, MAX_AGE);
    }

    function checked(TeachingPrice feed) private view returns (State, uint256, uint8) {
        (bool present, uint64 raw, uint8 digits, uint256 updated) = feed.quote();
        if (!present) return (State.Missing, 0, digits);
        if (raw == 0) return (State.BadAnswer, 0, digits);
        if (updated == 0 || updated > block.timestamp) return (State.BadTime, 0, digits);
        if (block.timestamp - updated > MAX_AGE) return (State.Stale, 0, digits);
        return (State.Ready, raw, digits);
    }

    // Only Ready has a metrics payload; other variants' zero ABI words carry no value.
    function inspect() external view returns (State, Side, Metrics memory m) {
        if (debt == 0) return (State.NoDebt, Side.Neither, m);
        (State cs, uint256 cp, uint8 cd) = checked(colFeed);
        if (cs != State.Ready) return (cs, Side.Collateral, m);
        (State ds, uint256 dp, uint8 dd) = checked(noteFeed);
        if (ds != State.Ready) return (ds, Side.Debt, m);

        m.collateralQ8 = uint256(collateral) * cp * Q_SCALE / (uint256(10) ** (COL_DIGITS + cd));
        uint256 numerator = uint256(debt) * dp * Q_SCALE;
        uint256 divisor = uint256(10) ** (NOTE_DIGITS + dd);
        m.debtQ8 = (numerator + divisor - 1) / divisor; // Positive debt never rounds to zero.
        m.adjustedQ8 = m.collateralQ8 * LT_BPS / BPS;
        m.hfWad = m.adjustedQ8 * 1e18 / m.debtQ8;
        uint256 borrowingLimit = m.collateralQ8 * LTV_BPS / BPS;
        m.headroomQ8 = borrowingLimit > m.debtQ8 ? borrowingLimit - m.debtQ8 : 0;
        return (State.Ready, Side.Neither, m);
    }
}
