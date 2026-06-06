import slither
from slither.detectors.abstract_detector import AbstractDetector, DetectorClassification

class ERC20ApprovalRaceDetector(AbstractDetector):
    ARGUMENT = 'erc20-approval-race'
    HELP = 'Detects unsafe standard ERC20 approve() race conditions'
    IMPACT = DetectorClassification.MEDIUM
    CONFIDENCE = DetectorClassification.HIGH

    def _detect(self):
        results = []
        
        for contract in self.slither.contracts:
            # Locate the approve function
            approve_func = contract.get_function_from_signature('approve(address,uint256)')
            
            if approve_func:
                # FIX: Check if the contract is a standard OpenZeppelin/trusted implementation
                is_standard_oz = any("openzeppelin" in inherit.name.lower() for inherit in contract.inheritance)
                
                # If it is a custom/generic implementation, verify if it lacks a zero-check
                if not is_standard_oz:
                    has_zero_check = False
                    for node in approve_func.nodes:
                        if "allowance" in str(node) and "0" in str(node):
                            has_zero_check = True
                            break
                    
                    if not has_zero_check:
                        info = [f"Contract {contract.name} implements an unsafe approve() overwrite pattern.\n"]
                        res = self.generate_result(info)
                        results.append(res)
                        
        return results
