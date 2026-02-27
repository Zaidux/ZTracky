// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

/**
 * @title  ZTrackySubscription
 * @notice Manages ZTracky Premium subscriptions and allows the admin to
 *         transfer ETH or ERC-20 tokens to any wallet/chain address.
 *         Deploy on any EVM-compatible network (Ethereum, Polygon, BSC …).
 *
 * ┌─────────────────────────────────────────────────────────────────────┐
 * │  SECURITY NOTES                                                     │
 * │  • No external calls are made before state mutations (CEI pattern). │
 * │  • Overpayment refunds use .call to avoid hard-coded gas limits.    │
 * │  • Re-entrancy on subscribe() is safe: state is updated first.      │
 * │  • Admin-only functions revert with custom errors (gas-efficient).  │
 * └─────────────────────────────────────────────────────────────────────┘
 */
contract ZTrackySubscription {

    // ─── Types ────────────────────────────────────────────────────────────
    address public immutable owner;
    uint256 public subscriptionPrice;           // wei per subscription period
    uint256 public constant PERIOD = 30 days;
    uint256 public totalRevenue;                // cumulative ETH collected (wei)

    mapping(address => uint256) public subscriptionExpiry;
    mapping(address => uint256) public paymentCount;

    // ─── Events ───────────────────────────────────────────────────────────
    event Subscribed(address indexed subscriber, uint256 expiry, uint256 paid);
    event PriceUpdated(uint256 oldPrice, uint256 newPrice);
    event ETHTransferred(address indexed to, uint256 amount, string note);
    event ERC20Transferred(address indexed token, address indexed to, uint256 amount);
    event Withdrawn(address indexed to, uint256 amount);

    // ─── Errors ───────────────────────────────────────────────────────────
    error NotOwner();
    error InsufficientPayment(uint256 sent, uint256 required);
    error ZeroAmount();
    error TransferFailed();

    // ─── Modifier ─────────────────────────────────────────────────────────
    modifier onlyOwner() {
        if (msg.sender != owner) revert NotOwner();
        _;
    }

    // ─── Constructor ──────────────────────────────────────────────────────
    /**
     * @param _subscriptionPrice  Monthly price in wei
     *        e.g. 0.005 ether = 5_000_000_000_000_000
     */
    constructor(uint256 _subscriptionPrice) {
        owner = msg.sender;
        subscriptionPrice = _subscriptionPrice;
    }

    // ─── User-facing ──────────────────────────────────────────────────────

    /**
     * @notice Subscribe or renew Premium for PERIOD days.
     *         Excess ETH is refunded automatically.
     */
    function subscribe() external payable {
        uint256 price = subscriptionPrice;
        if (msg.value < price) revert InsufficientPayment(msg.value, price);

        // Update state before any external call (Checks-Effects-Interactions)
        uint256 base = subscriptionExpiry[msg.sender];
        if (base < block.timestamp) base = block.timestamp;
        subscriptionExpiry[msg.sender] = base + PERIOD;
        paymentCount[msg.sender]++;
        totalRevenue += price;

        emit Subscribed(msg.sender, subscriptionExpiry[msg.sender], price);

        // Refund excess.
        // Note: if the refund call fails the entire transaction reverts (Solidity atomicity),
        // so the subscription state update above is also undone — no inconsistency can occur.
        uint256 excess = msg.value - price;
        if (excess > 0) {
            (bool ok, ) = payable(msg.sender).call{value: excess}("");
            require(ok, "Refund failed");
        }
    }

    /**
     * @notice Returns true when `user` holds an active subscription.
     */
    function isSubscribed(address user) external view returns (bool) {
        return subscriptionExpiry[user] >= block.timestamp;
    }

    // ─── Admin: subscription management ──────────────────────────────────

    /** @notice Update the subscription price (wei). */
    function setPrice(uint256 newPrice) external onlyOwner {
        emit PriceUpdated(subscriptionPrice, newPrice);
        subscriptionPrice = newPrice;
    }

    // ─── Admin: ETH transfers (wallet-to-wallet / cross-chain bridge) ─────

    /**
     * @notice Send ETH from contract balance to any address.
     *         Intended for the admin to move funds to another wallet or
     *         a cross-chain bridge contract.
     * @param  to      Recipient address (EOA or bridge contract)
     * @param  amount  Amount in wei
     * @param  note    Free-text memo (e.g. "Polygon bridge" / "operating")
     */
    function transferETH(
        address payable to,
        uint256 amount,
        string calldata note
    ) external onlyOwner {
        if (amount == 0) revert ZeroAmount();
        emit ETHTransferred(to, amount, note);
        (bool ok, ) = to.call{value: amount}("");
        if (!ok) revert TransferFailed();
    }

    /**
     * @notice Send ERC-20 tokens held by this contract to any address.
     * @param  token   ERC-20 contract address
     * @param  to      Recipient
     * @param  amount  Token amount (in token's smallest unit)
     */
    function transferERC20(
        address token,
        address to,
        uint256 amount
    ) external onlyOwner {
        if (amount == 0) revert ZeroAmount();
        // Low-level call avoids depending on an ERC-20 interface import
        (bool ok, bytes memory data) = token.call(
            abi.encodeWithSignature("transfer(address,uint256)", to, amount)
        );
        require(ok && (data.length == 0 || abi.decode(data, (bool))), "ERC20 transfer failed");
        emit ERC20Transferred(token, to, amount);
    }

    // ─── Admin: withdraw all ETH ──────────────────────────────────────────

    /** @notice Withdraw entire ETH balance to the owner's address. */
    function withdraw() external onlyOwner {
        uint256 balance = address(this).balance;
        emit Withdrawn(owner, balance);
        (bool ok, ) = payable(owner).call{value: balance}("");
        if (!ok) revert TransferFailed();
    }

    // ─── Views ────────────────────────────────────────────────────────────

    /** @notice Returns the contract's current ETH balance. */
    function contractBalance() external view returns (uint256) {
        return address(this).balance;
    }

    /** @notice Allows contract to receive plain ETH transfers. */
    receive() external payable {}
}
