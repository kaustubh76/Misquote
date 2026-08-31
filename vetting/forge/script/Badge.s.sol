// SPDX-License-Identifier: MIT
pragma solidity =0.7.6;
pragma abicoder v2;

/// @title Badge — a badge finding, executed against a forked chain.
/// @notice The second half of "they flag, we prove".
///
/// `packages/misquote/vetting/badge.py` reads nine checks off chain and writes
/// a verdict. Every one of them is a **sentence**: a FAIL says a pool cannot be
/// provided to and a reader has to take that on trust. This script makes three
/// of them transactions that either revert or do not, on a mainnet fork, at a
/// block the badge names.
///
/// Which three, and why not nine: a finding earns a proof-of-concept when the
/// consequence is something a transaction can *demonstrate*. `decimals read`
/// is a reading — there is nothing to execute. `a mintable range exists` is a
/// claim about whether `mint` reverts, and that is exactly what a fork can
/// settle. The other six are recorded here as deliberately unproven rather than
/// left to look like an oversight; see `PROVEN` in `vetting/proof.py`.
///
/// Run through `python -m misquote.vetting.proof`, which supplies the fork url
/// and the badge's own recorded values as environment variables so this script
/// cannot quietly test a different pool from the one that was flagged.
interface IPool {
    function slot0()
        external
        view
        returns (uint160, int24, uint16, uint16, uint16, uint32, bool);

    function tickSpacing() external view returns (int24);

    function liquidity() external view returns (uint128);

    function factory() external view returns (address);

    function fee() external view returns (uint24);

    function token0() external view returns (address);

    function token1() external view returns (address);
}

interface IFactory {
    function getPool(address, address, uint24) external view returns (address);
}

/// @notice The NonfungiblePositionManager, hand-declared.
///
/// v3-periphery vendors `INonfungiblePositionManager` and it is unimportable: it
/// pulls OpenZeppelin's `IERC721Metadata` from a remapped path, and there is
/// no OpenZeppelin on disk and no remapping for it. forge-std is no help either -
/// every file in it declares `pragma solidity >=0.8.13 <0.9.0` against this
/// project's deliberate `solc = "0.7.6"` pin, so there is no `vm.deal`, no
/// `vm.prank` and no `Script.sol`. `Badge.s.sol` imports nothing for that reason;
/// this follows it.
///
/// The struct shape is mirrored from `chain/nfpm.py::NFPM_ABI`, whose canonical
/// selector string is recorded there as
/// `mint((address,address,uint24,int24,int24,uint256,uint256,uint256,uint256,address,uint256))`.
interface INFPM {
    struct MintParams {
        address token0;
        address token1;
        uint24 fee;
        int24 tickLower;
        int24 tickUpper;
        uint256 amount0Desired;
        uint256 amount1Desired;
        uint256 amount0Min;
        uint256 amount1Min;
        address recipient;
        uint256 deadline;
    }

    function mint(MintParams calldata params)
        external
        payable
        returns (uint256 tokenId, uint128 liquidity, uint256 amount0, uint256 amount1);
}

interface IERC20 {
    function approve(address spender, uint256 amount) external returns (bool);

    function balanceOf(address account) external view returns (uint256);
}

contract BadgeProof {
    /// @dev Thrown with the id of the check whose claim did not hold, so a
    /// failure names a finding rather than a line number.
    event Proved(string id, bool held, string detail);

    /// @notice Accept the position NFT. Without this, `proveMintable` cannot work.
    ///
    /// A v3 position **is** an ERC-721, and the position manager mints it to
    /// `recipient`. A contract recipient that does not implement this is rejected
    /// by the transfer, so the mint reverts — and it reverts with **empty return
    /// data**, so `catch Error(string)` never fires and the honest report is "no
    /// reason given".
    ///
    /// That is exactly how this was found: identical parameters minted from an
    /// EOA with `status: 1` and reverted from here with nothing to say. The
    /// difference between the two calls was not the range, the tokens, the
    /// approvals or the bounds — it was who was being handed the token.
    ///
    /// Returns the ERC-721 magic value, `bytes4(keccak256(
    /// "onERC721Received(address,address,uint256,bytes)"))`.
    function onERC721Received(address, address, uint256, bytes calldata)
        external
        pure
        returns (bytes4)
    {
        return 0x150b7a02;
    }

    /// `factory` — P-6. The badge claims `factory.getPool(t0, t1, fee)` returns
    /// this pool. Pancake deploys through a separate `PancakeV3PoolDeployer`
    /// with a different init-code hash, so Uniswap's `computeAddress` constants
    /// yield a **plausible address that is not the pool** — an error that costs
    /// an LP their whole position if they act on it.
    ///
    /// Executed rather than asserted: this resolves through the factory the
    /// pool itself names, so a wrong answer here is the pool disowning itself.
    function proveFactory(address pool) external returns (bool held) {
        IPool p = IPool(pool);
        address resolved = IFactory(p.factory()).getPool(p.token0(), p.token1(), p.fee());
        held = resolved == pool;
        emit Proved(
            "factory",
            held,
            held ? "getPool returns this pool" : "getPool returns a different address"
        );
    }

    /// `tick-spacing` — P-6 again, and the reason `MIN_TICK % 10 == 2` matters.
    /// The badge claims a range on the tick grid can be built. This computes the
    /// same bounds the badge does and checks they are on the pool's own grid;
    /// a range off the grid is one the pool rejects at transaction time, which
    /// is the worst moment to find out.
    function proveTickSpacing(address pool, int24 lower, int24 upper)
        external
        returns (bool held)
    {
        int24 spacing = IPool(pool).tickSpacing();
        held = spacing != 0 && lower % spacing == 0 && upper % spacing == 0 && lower < upper;
        emit Proved(
            "tick-spacing",
            held,
            held ? "both bounds sit on the pool's grid" : "a bound is off the tick grid"
        );
    }

    /// `mintable-range` — V-10, and the one check here whose consequence is a
    /// transaction rather than a reading.
    ///
    /// The badge claims a range exists that the pool will accept. Every other
    /// prover in this file reads state and compares it; this one **sends a mint**
    /// and reports whether the NonfungiblePositionManager took it. `MIN_TICK % 10
    /// == 2` on this pool's spacing, so clamping to the grid naively yields ticks
    /// the pool rejects — and it rejects them at transaction time, which is the
    /// worst moment to find out.
    ///
    /// Three things this deliberately does:
    ///
    /// - **`amount0Min` and `amount1Min` are passed as 0 by the caller**, not
    ///   bounded here. `chain/nfpm.py` records that bounding both at 99.5% of
    ///   desired reverts every time, because the curve consumes tokens in the
    ///   price-dictated ratio rather than the requested one. The claim under test
    ///   is only that the mint does not revert; a slippage bound would make it
    ///   fail for an unrelated reason and read as the finding being false.
    /// - **It holds the tokens and approves itself.** This contract is
    ///   `msg.sender` to the NFPM, so `recipient` is `address(this)` and Python
    ///   funds this address before calling.
    /// - **`try/catch`, not a bare call.** A revert is the answer, and the answer
    ///   has to reach the event rather than the transaction.
    function proveMintable(
        address nfpm,
        address pool,
        int24 lower,
        int24 upper,
        uint256 amount0,
        uint256 amount1
    ) external returns (bool held) {
        IPool p = IPool(pool);
        address t0 = p.token0();
        address t1 = p.token1();

        IERC20(t0).approve(nfpm, amount0);
        IERC20(t1).approve(nfpm, amount1);

        INFPM.MintParams memory params = INFPM.MintParams({
            token0: t0,
            token1: t1,
            fee: p.fee(),
            tickLower: lower,
            tickUpper: upper,
            amount0Desired: amount0,
            amount1Desired: amount1,
            amount0Min: 0,
            amount1Min: 0,
            recipient: address(this),
            deadline: block.timestamp + 1200
        });

        try INFPM(nfpm).mint(params) returns (uint256 tokenId, uint128 liq, uint256, uint256) {
            held = tokenId > 0 && liq > 0;
            emit Proved(
                "mintable-range",
                held,
                held
                    ? "the position manager accepted a mint at the badge's bounds"
                    : "the mint returned no position"
            );
        } catch Error(string memory reason) {
            // The revert *string*, not the fact of a revert. "the mint reverted"
            // is a result nobody can act on; "Price slippage check" names the
            // trap, and this repository has already paid for that one once.
            held = false;
            emit Proved(
                "mintable-range",
                false,
                string(abi.encodePacked("the mint reverted: ", reason))
            );
        } catch (bytes memory data) {
            // A custom error or an out-of-gas: no string to recover. Report the
            // selector rather than nothing, so it can be resolved the way
            // `hire.CREATE_JOB_ERRORS` resolved createJob's.
            held = false;
            emit Proved(
                "mintable-range",
                false,
                string(abi.encodePacked("the mint reverted with ", _hex4(data), " and no reason"))
            );
        }
    }

    /// The first four bytes of a revert payload, as `0x…` text.
    function _hex4(bytes memory data) private pure returns (string memory) {
        if (data.length < 4) return "no data";
        bytes memory alphabet = "0123456789abcdef";
        bytes memory out = new bytes(10);
        out[0] = "0";
        out[1] = "x";
        for (uint256 i = 0; i < 4; i++) {
            out[2 + i * 2] = alphabet[uint8(data[i]) >> 4];
            out[3 + i * 2] = alphabet[uint8(data[i]) & 0x0f];
        }
        return string(out);
    }

    /// `liquidity-depth` — A1. The badge claims the pool is deep enough that a
    /// position sized to assumption A1's share is not dust. Read at the forked
    /// block rather than taken from the badge, so a badge recorded against a
    /// pool that has since been drained fails here.
    function proveLiquidity(address pool, uint128 floor) external returns (bool held) {
        uint128 live = IPool(pool).liquidity();
        held = live >= floor;
        emit Proved(
            "liquidity-depth",
            held,
            held ? "pool liquidity is at or above the floor" : "pool liquidity is below the floor"
        );
    }
}
