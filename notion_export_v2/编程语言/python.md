- **函数**
	python中参数一般都是以引用传递传入,但是如果原始对象不可变类型(int 元组 字符),那就还是值类型不会修改原始值
	Python中方法也分成了实例方法、静态方法和类方法
- **Python支持多继承**
- **类装饰器 修饰函数用来定义一些行为**
	- 单例模式（Singleton）：类装饰器可以用于实现单例模式，确保一个类只有一个实例。
	- 计时器（Timer）：类装饰器可以用于测量类中所有方法的执行时间
	- 访问控制（Access Control）：类装饰器可以用于实现访问控制，例如限制某些方法的访问
```python
python复制代码
def singleton(cls):
    instances = {}

    def get_instance(*args, **kwargs):
        if cls not in instances:
            instances[cls] = cls(*args, **kwargs)
        return instances[cls]

    return get_instance

@singleton
class MyClass:
    pass

instance1 = MyClass()
instance2 = MyClass()
print(instance1 is instance2)# 输出 True
```
```python
python复制代码
import time

def timer(cls):
    class Wrapper:
        def __init__(self, *args, **kwargs):
            self.wrapped = cls(*args, **kwargs)

        def __getattr__(self, name):
            attr = getattr(self.wrapped, name)
            if callable(attr):
                def timed(*args, **kwargs):
                    start = time.time()
                    result = attr(*args, **kwargs)
                    print(f"Time elapsed: {time.time() - start}")
                    return result

                return timed
            return attr

    return Wrapper

@timer
class MyClass:
    def method(self):
        time.sleep(1)

my_instance = MyClass()
my_instance.method()# 输出 "Time elapsed: 1.001..."
```
```python
python复制代码
def protected_methods(*methods):
    def class_decorator(cls):
        class Wrapper:
            def __init__(self, *args, **kwargs):
                self.wrapped = cls(*args, **kwargs)

            def __getattr__(self, name):
                attr = getattr(self.wrapped, name)
                if name in methods:
                    raise AttributeError(f"Access to the method '{name}' is not allowed.")
                return attr

        return Wrapper

    return class_decorator

@protected_methods("protected_method")
class MyClass:
    def public_method(self):
        print("This is a public method.")

    def protected_method(self):
        print("This is a protected method.")

my_instance = MyClass()
my_instance.public_method()
my_instance.protected_method()# 抛出 AttributeError
```