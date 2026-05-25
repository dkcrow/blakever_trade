"""
测试模块 - Tests Module
包含所有测试用例
"""

import unittest

def run_all_tests():
    """运行所有测试"""
    loader = unittest.TestLoader()
    suite = loader.discover(start_dir='.', pattern='test_*.py')
    runner = unittest.TextTestRunner(verbosity=2)
    runner.run(suite)

if __name__ == '__main__':
    run_all_tests()
