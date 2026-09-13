import unittest
from PIL import Image,ImageDraw
from BrowserToolLayout import build_browser_tool_action,plan_browser_tools
from Version import APP_VERSION,FILE_VERSION

class BrowserToolLayoutV10145Tests(unittest.TestCase):
    def mock(self):
        client=(0,0,1200,900);canvas=(200,160,900,630)
        image=Image.new('RGB',(1200,900),(236,236,236));draw=ImageDraw.Draw(image)
        x0,y0,x1,y1=canvas;w,h=x1-x0,y1-y0
        top_gap=max(22,min(int(900*.055),int(h*.14)));right_gap=max(26,min(int(1200*.055),int(w*.18)))
        row=max(26,min(int(h*.115),int(900*.090)))
        points={'Brush':(x0+int(w*.060),y0-top_gap),'Eraser':(x1-int(w*.060),y0-top_gap),'Fill':(x1+right_gap,y0+int(row*1.15)),'Clear':(x1+right_gap,y0+int(row*2.20))}
        for x,y in points.values():draw.ellipse((x-12,y-12,x+12,y+12),fill=(28,28,28))
        return image,client,canvas
    def test_version(self):
        self.assertEqual((APP_VERSION,FILE_VERSION),('1.0.145-rc29','1.0.145'))
    def test_gartic_phone_tools(self):
        image,client,canvas=self.mock();plan=plan_browser_tools('gartic-phone',image,client,canvas_box=canvas)
        self.assertGreaterEqual(plan.confidence,.58);self.assertEqual(set(plan.tools),{'Brush','Fill','Eraser','Clear'})
    def test_gartic_io_tools_and_action(self):
        image,client,canvas=self.mock();plan=plan_browser_tools('gartic-io',image,client,canvas_box=canvas)
        kind,pos=build_browser_tool_action(plan.as_dict(),'Brush');self.assertEqual(kind,'brush');self.assertEqual(tuple(pos),plan.tools['Brush'])
    def test_low_confidence_fails_closed(self):
        with self.assertRaises(ValueError):build_browser_tool_action({'tools':{'Brush':[10,10]},'confidence':.2},'Brush')

if __name__=='__main__':unittest.main()
