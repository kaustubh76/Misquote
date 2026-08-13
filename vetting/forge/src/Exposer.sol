// SPDX-License-Identifier: MIT
pragma solidity =0.7.6;
pragma abicoder v2;

import '@uniswap/v3-core/contracts/libraries/TickMath.sol';
import '@uniswap/v3-core/contracts/libraries/SqrtPriceMath.sol';
import '@uniswap/v3-core/contracts/libraries/FullMath.sol';
import '@uniswap/v3-core/contracts/libraries/FixedPoint128.sol';
import '@uniswap/v3-core/contracts/libraries/Tick.sol';
import '@uniswap/v3-periphery/contracts/libraries/LiquidityAmounts.sol';

/// @title Exposer — the reference implementation, made callable.
/// @notice Wraps the real v3 libraries so a differential harness can ask them
/// what the answer is. This contract adds no arithmetic of its own; every
/// function body is a single delegation, so anything it returns is what a
/// PancakeSwap pool would compute for the same inputs.
///
/// PancakeSwap v3 uses Uniswap v3's core math unchanged, so the upstream
/// Uniswap sources are the faithful reference. Both are vendored at pinned
/// commits recorded in ops/forge_deps.txt.
contract Exposer {
    // --- TickMath ----------------------------------------------------------

    function getSqrtRatioAtTick(int24 tick) external pure returns (uint160) {
        return TickMath.getSqrtRatioAtTick(tick);
    }

    function getTickAtSqrtRatio(uint160 sqrtPriceX96) external pure returns (int24) {
        return TickMath.getTickAtSqrtRatio(sqrtPriceX96);
    }

    function minTick() external pure returns (int24) {
        return TickMath.MIN_TICK;
    }

    function maxTick() external pure returns (int24) {
        return TickMath.MAX_TICK;
    }

    function minSqrtRatio() external pure returns (uint160) {
        return TickMath.MIN_SQRT_RATIO;
    }

    function maxSqrtRatio() external pure returns (uint160) {
        return TickMath.MAX_SQRT_RATIO;
    }

    // --- SqrtPriceMath: the pool's rounding-directional deltas --------------

    function getAmount0Delta(
        uint160 sqrtRatioAX96,
        uint160 sqrtRatioBX96,
        uint128 liquidity,
        bool roundUp
    ) external pure returns (uint256) {
        return SqrtPriceMath.getAmount0Delta(sqrtRatioAX96, sqrtRatioBX96, liquidity, roundUp);
    }

    function getAmount1Delta(
        uint160 sqrtRatioAX96,
        uint160 sqrtRatioBX96,
        uint128 liquidity,
        bool roundUp
    ) external pure returns (uint256) {
        return SqrtPriceMath.getAmount1Delta(sqrtRatioAX96, sqrtRatioBX96, liquidity, roundUp);
    }

    function getAmount0DeltaSigned(
        uint160 sqrtRatioAX96,
        uint160 sqrtRatioBX96,
        int128 liquidity
    ) external pure returns (int256) {
        return SqrtPriceMath.getAmount0Delta(sqrtRatioAX96, sqrtRatioBX96, liquidity);
    }

    function getAmount1DeltaSigned(
        uint160 sqrtRatioAX96,
        uint160 sqrtRatioBX96,
        int128 liquidity
    ) external pure returns (int256) {
        return SqrtPriceMath.getAmount1Delta(sqrtRatioAX96, sqrtRatioBX96, liquidity);
    }

    // --- LiquidityAmounts: what the position manager reports ----------------

    function getLiquidityForAmount0(
        uint160 sqrtRatioAX96,
        uint160 sqrtRatioBX96,
        uint256 amount0
    ) external pure returns (uint128) {
        return LiquidityAmounts.getLiquidityForAmount0(sqrtRatioAX96, sqrtRatioBX96, amount0);
    }

    function getLiquidityForAmount1(
        uint160 sqrtRatioAX96,
        uint160 sqrtRatioBX96,
        uint256 amount1
    ) external pure returns (uint128) {
        return LiquidityAmounts.getLiquidityForAmount1(sqrtRatioAX96, sqrtRatioBX96, amount1);
    }

    function getLiquidityForAmounts(
        uint160 sqrtRatioX96,
        uint160 sqrtRatioAX96,
        uint160 sqrtRatioBX96,
        uint256 amount0,
        uint256 amount1
    ) external pure returns (uint128) {
        return
            LiquidityAmounts.getLiquidityForAmounts(
                sqrtRatioX96,
                sqrtRatioAX96,
                sqrtRatioBX96,
                amount0,
                amount1
            );
    }

    function getAmount0ForLiquidity(
        uint160 sqrtRatioAX96,
        uint160 sqrtRatioBX96,
        uint128 liquidity
    ) external pure returns (uint256) {
        return LiquidityAmounts.getAmount0ForLiquidity(sqrtRatioAX96, sqrtRatioBX96, liquidity);
    }

    function getAmount1ForLiquidity(
        uint160 sqrtRatioAX96,
        uint160 sqrtRatioBX96,
        uint128 liquidity
    ) external pure returns (uint256) {
        return LiquidityAmounts.getAmount1ForLiquidity(sqrtRatioAX96, sqrtRatioBX96, liquidity);
    }

    function getAmountsForLiquidity(
        uint160 sqrtRatioX96,
        uint160 sqrtRatioAX96,
        uint160 sqrtRatioBX96,
        uint128 liquidity
    ) external pure returns (uint256 amount0, uint256 amount1) {
        return
            LiquidityAmounts.getAmountsForLiquidity(
                sqrtRatioX96,
                sqrtRatioAX96,
                sqrtRatioBX96,
                liquidity
            );
    }

    // --- Fee growth: the wraparound path ------------------------------------
    //
    // Tick.getFeeGrowthInside reads tick state from storage, so the harness
    // seeds two ticks and then asks. That keeps the call on the real library
    // rather than on a reimplementation of it, which matters more here than
    // anywhere else: this is the code path whose unchecked subtraction a naive
    // Python translation gets catastrophically wrong.

    mapping(int24 => Tick.Info) public ticks;

    function setTick(
        int24 tick,
        uint256 feeGrowthOutside0X128,
        uint256 feeGrowthOutside1X128
    ) external {
        Tick.Info storage info = ticks[tick];
        info.feeGrowthOutside0X128 = feeGrowthOutside0X128;
        info.feeGrowthOutside1X128 = feeGrowthOutside1X128;
        info.initialized = true;
    }

    function getFeeGrowthInside(
        int24 tickLower,
        int24 tickUpper,
        int24 tickCurrent,
        uint256 feeGrowthGlobal0X128,
        uint256 feeGrowthGlobal1X128
    ) external view returns (uint256 feeGrowthInside0X128, uint256 feeGrowthInside1X128) {
        return
            Tick.getFeeGrowthInside(
                ticks,
                tickLower,
                tickUpper,
                tickCurrent,
                feeGrowthGlobal0X128,
                feeGrowthGlobal1X128
            );
    }

    /// @notice The exact expression Position.update uses to convert a change in
    /// inside fee growth into tokens owed. Reproduced rather than delegated
    /// because Position.update also mutates storage and returns nothing.
    function tokensOwed(
        uint256 feeGrowthInsideLastX128,
        uint256 feeGrowthInsideNowX128,
        uint128 liquidity
    ) external pure returns (uint128) {
        return
            uint128(
                FullMath.mulDiv(
                    feeGrowthInsideNowX128 - feeGrowthInsideLastX128,
                    liquidity,
                    FixedPoint128.Q128
                )
            );
    }

    // --- FullMath, for its own sake -----------------------------------------

    function mulDiv(uint256 a, uint256 b, uint256 denominator) external pure returns (uint256) {
        return FullMath.mulDiv(a, b, denominator);
    }

    function mulDivRoundingUp(
        uint256 a,
        uint256 b,
        uint256 denominator
    ) external pure returns (uint256) {
        return FullMath.mulDivRoundingUp(a, b, denominator);
    }
}
