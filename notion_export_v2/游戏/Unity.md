<details>
<summary>**fixedupdate是固定时间调用 不受帧率影响 **</summary>
	也就是哪怕你暂停游戏也不会影响它的定时调用。
	但如果游戏性能有大问题 显然也会影响它的调用次数 
</details>
<details>
<summary>**Unity** **Shader**</summary>
	<details>
	<summary>**API**</summary>
		1.float3 WorldSpaceViewDir(float4 v)    输入模型坐标下的顶点位置a,返回世界坐标下从a到摄像机的向量(这个好,直接vetex.pos作为参数)
		2.float3  UnityWorldSpaceViewDir(float4 v)  输入世界坐标下的顶点位置a,返回世界坐标下从a到摄像机的向量(这个还要先把vetex.pos转换为世界坐标下的 通过     mul(UNITY_MATRIX_MVP,vetex.pos);)
		3.float3 ObjSpaceViewDir(float4 v)  输入模型坐标 点 a ,返回从模型空间中该点到摄像机的向量
		4.float3 WorldSpaceLightDir(float4 v) 输入模型坐标中的顶点位置,返回世界空间中该点到光源的方向 (仅用于前向渲染)
		5.float3 UnityWorldSpaceLightDir(float4 v)  输入世界坐标中的顶点位置,返回世界空间中该点到光源的方向 (仅用于前向渲染)
		6.ObjSpaceLightDir(float4 v)输入模型坐标中的顶点位置,返回模型空间中该点到光源的方向 (仅用于前向渲染)
		7.UnityObjectToWorldNormal(float3) 法线从模型坐标转到世界坐标
		8.UnityObjectToWorldDir(float3 dir)  一个模型坐标中计算完成的向量 通过该函数可以转换到世界坐标下
		9.UnityWorldToObjectDir(float3 dir)  一个世界坐标中计算完成的向量 通过该函数可以转换到模型坐标下
		以上函数计算后需要normalize才能正常使用
	</details>
	<details>
	<summary>**vetex/frag中纹理坐标的传输**</summary>
		1. 定义一个sampler2d maintex;
		2.         struct a2v
		\{
		float4 tex:TEXCOORD0;//这样就能获取第一组纹理maintex的xyzw
		\};
		3.          struct v2f
		\{
		float2 uv:TEXCOORD10;//这样是为了获取在顶点着色器中变换后的tex的xyzw信息(因为a2v中存储的坐标只是模型坐标下的,而我们要世界坐标的)
		\};
		4.通过out.uv=TRANSFORM_TEX(vetex.tex,mainTex);//这个函数等价于于o.uv=v.texcoord.xy\*+mainTex_ST.xy+_MainTex_ST.zw;
		就能完成纹理从模型坐标到模型坐标的转换 out.uv在这里可以解释为mainTex在片元着色器上的uv缩放偏移信息
		5.注意上面的红色float2 说明out.uv=TRANSFORM_TEX(vetex.tex,mainTex);其实是把纹理的缩放偏移放到了一个float2里面就足够了,而有时需要凹凸纹理,会选用 float4 uv:TEXCOORD10;这样的,然后out.uv.xy存放maintex的纹理缩放偏移  , out.uv.zw 用来存放 凹凸纹理的缩放偏移
	</details>
	<details>
	<summary>**uv值的取值范围是(0,1) **</summary>
		所以你在frag里写 i.uv+=float2(100,100)这种都是没用的,只会截断或者重复要写i.uv+=float2(0.5,0.5)
	</details>
</details>
<empty-block/>