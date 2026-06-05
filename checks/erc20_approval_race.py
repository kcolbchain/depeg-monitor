from slither.detectors.abstract_detector import AbstractDetector, DetectorClassification

class ERC20ApprovalRace(AbstractDetector):
    """
    Detects the ERC20 approve() race condition vulnerability.
    """
    ARGUMENT = 'erc20-approval-race'
    HELP = 'ERC20 approve() race condition (Front-running vulnerability)'
    IMPACT = DetectorClassification.HIGH
    CONFIDENCE = DetectorClassification.HIGH

    WIKI = 'https://github.com/ethereum/EIPs/issues/20#issuecomment-263524729'
    WIKI_TITLE = 'ERC20 API: An Attack Vector on the Approve/TransferFrom Methods'
    WIKI_DESCRIPTION = 'The standard ERC20 implementation contains a widely known race condition in the approve function.'
    WIKI_RECOMMENDATION = 'Use safe increaseAllowance and decreaseAllowance mitigations instead of direct state overwriting.'

    def _detect(self):
        results = []
        for contract in self.compilation_unit.contracts_derived:
            # Check if the contract implements the vulnerable approve signature
            approve_func = contract.get_function_from_signature('approve(address,uint256)')
            
            if approve_func:
                # If they have approve, they must also implement mitigations
                has_increase = contract.get_function_from_signature('increaseAllowance(address,uint256)')
                has_decrease = contract.get_function_from_signature('decreaseAllowance(address,uint256)')
                
                if not has_increase or not has_decrease:
                    info = [
                        contract, 
                        " implements approve(address,uint256) but is missing increaseAllowance/decreaseAllowance mitigations. Susceptible to double-spend front-running.\n"
                    ]
                    res = self.generate_result(info)
                    results.append(res)
                    
        return results
