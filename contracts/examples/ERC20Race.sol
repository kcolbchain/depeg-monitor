// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

contract ERC20RaceVulnerable {
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    constructor() {
        // Mint initial tokens to the deployer for testing
        balanceOf[msg.sender] = 10000;
    }

    function transfer(address recipient, uint256 amount) public returns (bool) {
        require(balanceOf[msg.sender] >= amount, "Insufficient balance");
        balanceOf[msg.sender] -= amount;
        balanceOf[recipient] += amount;
        return true;
    }

    // VULNERABLE: Overwrites state without checking previous pending spends
    function approve(address spender, uint256 amount) public returns (bool) {
        allowance[msg.sender][spender] = amount;
        return true;
    }

    function transferFrom(address sender, address recipient, uint256 amount) public returns (bool) {
        require(allowance[sender][msg.sender] >= amount, "Insufficient allowance");
        require(balanceOf[sender] >= amount, "Insufficient balance");
        
        allowance[sender][msg.sender] -= amount;
        balanceOf[sender] -= amount;
        balanceOf[recipient] += amount;
        return true;
    }

    // MITIGATED: Safe increase pattern
    function increaseAllowance(address spender, uint256 addedValue) public returns (bool) {
        allowance[msg.sender][spender] += addedValue;
        return true;
    }

    // MITIGATED: Safe decrease pattern
    function decreaseAllowance(address spender, uint256 subtractedValue) public returns (bool) {
        uint256 currentAllowance = allowance[msg.sender][spender];
        require(currentAllowance >= subtractedValue, "ERC20: decreased allowance below zero");
        allowance[msg.sender][spender] = currentAllowance - subtractedValue;
        return true;
    }
}
