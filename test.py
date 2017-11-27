def foo(a=(1,2,3)):
    if 1 in a:
        print('ok')
    else:
        print('no')


foo(a=[4,1])
