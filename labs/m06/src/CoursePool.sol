// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

interface IPoolToken {
    function balanceOf(address owner) external view returns (uint256);
    function transfer(address to, uint256 amount) external returns (bool);
    function transferFrom(address from, address to, uint256 amount) external returns (bool);
}

/// Single direction, two known LabTokens, local chain only. Seed by transferring
/// tokens to this address; balances are the reserves. No LP shares or withdrawal.
contract CoursePool {
    IPoolToken public immutable tokenIn;
    IPoolToken public immutable tokenOut;

    event Swap(address indexed trader, uint256 amountIn, uint256 amountOut);

    constructor(address input, address output) {
        require(input != output && input != address(0) && output != address(0), "pair");
        tokenIn = IPoolToken(input);
        tokenOut = IPoolToken(output);
    }

    function quote(uint256 amountIn) public view returns (uint256) {
        uint256 x = tokenIn.balanceOf(address(this));
        uint256 y = tokenOut.balanceOf(address(this));
        require(x != 0 && y != 0 && amountIn != 0, "empty reserve or input");
        uint256 withFee = amountIn * 997;
        return withFee * y / (1000 * x + withFee);
    }

    function swap(uint256 amountIn, uint256 minOut) external returns (uint256 amountOut) {
        amountOut = quote(amountIn);
        require(amountOut != 0 && amountOut >= minOut, "output below minimum");
        require(tokenIn.transferFrom(msg.sender, address(this), amountIn), "input transfer");
        require(tokenOut.transfer(msg.sender, amountOut), "output transfer");
        emit Swap(msg.sender, amountIn, amountOut);
    }
}
