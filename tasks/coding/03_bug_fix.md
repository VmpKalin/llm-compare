This Python function should return the second largest UNIQUE value in a list, or None if it does not exist. It has bugs. Return the corrected function in a single python code block named `second_largest`, no explanation.

def second_largest(nums):
    nums = sorted(nums)
    return nums[-2]
